"""
orchestrator_cad.py — Entrypoint to run fast-rlm.

Responsibilities:
  1. Define a hardcoded prompt payload, model configuration, and validation schema.
  2. Load user-defined tools (Python functions) to expose to the REPL.
  3. Invoke fast_rlm.run(...) to execute the recursive LLM loop.
  4. Output result and token usage stats.
"""

import os
import yaml
import json
import sys
import importlib.util
from pathlib import Path
from dotenv import load_dotenv
import fast_rlm
from tools import get_tools
from trace_view import render_trace

# Load environment variables from the .env file
load_dotenv()

# Ensure required environment variables are set before running
if not os.environ.get("RLM_MODEL_API_KEY"):
    raise RuntimeError("RLM_MODEL_API_KEY is missing. Please set it in your .env file.")

# Intelligent endpoint router:
api_key = os.environ.get("RLM_MODEL_API_KEY", "")
if api_key.startswith("AIzaSy") or api_key.startswith("AQ."):
    os.environ["RLM_MODEL_BASE_URL"] = "https://generativelanguage.googleapis.com/v1beta/openai"
    print(f"[INFO] Google Gemini API Key detected. Using endpoint: {os.environ['RLM_MODEL_BASE_URL']}")

DEFAULT_CONFIG_PATH = Path(__file__).parent / "run_cad.yaml"

CONFIG_KEYS = {
    "primary_agent", "sub_agent", "max_depth", "max_calls_per_subagent",
    "truncate_len", "max_money_spent", "max_completion_tokens",
    "max_prompt_tokens", "api_max_retries", "api_timeout_ms",
    "enable_tools", "enable_structured_io", "enable_compression_guard",
    "compression_min_chars", "compression_ratio",
}
LLM_KEYS = {"temperature", "top_p", "seed", "top_k",
            "presence_penalty", "frequency_penalty"}

UNSAFE_SKILL_TOKENS = (
    "cadquery",
    "cq.",
    "workplane",
    "import cadquery",
    "csg",
    "@jscad/modeling",
)


def load_run_config(path=DEFAULT_CONFIG_PATH):
    cfg = yaml.safe_load(open(path)) or {}
    config = {k: v for k, v in cfg.items() if k in CONFIG_KEYS and v is not None}
    llm_kwargs = {k: v for k, v in cfg.items() if k in LLM_KEYS and v is not None}
    flags = {k: v for k, v in cfg.items()
             if k not in CONFIG_KEYS and k not in LLM_KEYS and v is not None}
    return config, llm_kwargs, flags


def load_pydantic_schema(path: Path):
    """Dynamically load a Pydantic model from a Python file path."""
    module_name = path.stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from spec at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # If CADGenerationContainer is defined in the module, use it directly to enforce min_length
    container = getattr(module, "CADGenerationContainer", None)
    if container:
        print("[INFO] Using CADGenerationContainer schema with strict min_length=1 array validation.")
        return container

    from pydantic import BaseModel
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and issubclass(attr, BaseModel) and attr is not BaseModel:
            # Wrap the found BaseModel in list[...] since the output is expected to be a list
            return list[attr]
    raise ValueError(f"No Pydantic BaseModel subclass found in {path}")


def _read_text(path: Path) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _skill_is_forgecad_safe(path: Path) -> bool:
    if path.name in {"forgecad_designer.md", "forgecad_runtime_core.md", "forgecad_doc_index.md"}:
        return True
    text = _read_text(path).lower()
    return not any(token in text for token in UNSAFE_SKILL_TOKENS)


def select_forgecad_skills(skill_override: str | None, prompt: str | None = None) -> list[str]:
    selected_skills = []
    for skill_file in [
        skill_override or "skills/forgecad_designer.md",
        "skills/forgecad_runtime_core.md",
        "skills/forgecad_doc_index.md",
        "skills/forgecad_planner.md",
    ]:
        if skill_file not in selected_skills:
            selected_skills.append(skill_file)

    # Intelligent prompt-driven routing of expert companion skills
    if prompt:
        p_lower = prompt.lower()
        if any(keyword in p_lower for keyword in ["chair", "desk", "table", "assembly", "joint", "mate", "mechanism", "gear", "clamping", "mount"]):
            selected_skills.append("skills/forgecad-component-model.md")
        if any(keyword in p_lower for keyword in ["replicate", "photo", "image", "screenshot", "capture", "png", "jpg"]):
            selected_skills.append("skills/forgecad-image-replicator.md")
        if any(keyword in p_lower for keyword in ["blockout", "rough", "concept", "concept-car", "draft"]):
            selected_skills.append("skills/forgecad-blockout-model.md")

    return selected_skills


def main():
    # 1. Load Configurations
    config_path = DEFAULT_CONFIG_PATH
    custom_prompt = None
    
    # Check if arguments are provided
    if len(sys.argv) > 1:
        if sys.argv[1].endswith(".yaml"):
            config_path = Path(sys.argv[1])
            print(f"[INFO] Using custom configuration path: {config_path}")
            if len(sys.argv) > 2:
                custom_prompt = " ".join(sys.argv[2:])
        else:
            custom_prompt = " ".join(sys.argv[1:])
            
    config, llm_kwargs, flags = load_run_config(config_path)
    # Single-root-RLM mode: tools may help, but no recursive LLM subagents.
    config["max_depth"] = 0

    # If no custom prompt is passed on CLI, default to a robust solid triangle
    if not custom_prompt:
        custom_prompt = "Create a solid triangle using ngon(3, 30).extrude(10)."

    print(f"[INFO] Natural Language CAD Prompt: {custom_prompt}")

    # 2. Define payload for ForgeCAD generation task
    payload = {
        "role_instructions": "",
        "task_instructions": (
            "Generate a physical 3D CAD model for this user prompt:\n"
            f"{custom_prompt}\n\n"
            "Hard constraints:\n"
            "- Generate ForgeCAD JavaScript only.\n"
            "- Never use CadQuery, Python CAD code, OpenSCAD, JSCAD, CSG, or @jscad/modeling.\n"
            "- Never guess, invent, or assume any API names or signatures. You MUST use 'forgecad_api_lookup(symbol)' or 'forgecad_web_doc_lookup(topic)' to verify the exact signature of any function before writing it.\n"
            "- Use one root RLM only. Do not call llm_query and do not spawn subagents.\n"
            "- Do not create scratch output folders.\n"
            "- Do not use silent try/catch fallbacks.\n"
            "- Do not inspect or print full context, docs, schema, or role instructions.\n\n"
            "Terminal trace requirements:\n"
            "- Before each major action, print 'Step:', 'Reasoning summary:', and 'Next action:'.\n"
            "- Print the tool name and compact arguments before each tool call.\n"
            "- Print tool output summaries and full compiler/export errors.\n"
            "- Do not print hidden chain-of-thought; use concise visible reasoning summaries only.\n\n"
            "Required workflow:\n"
            "1. Call mcp_list_tools() exactly once to discover host tools.\n"
            "2. Call forgecad_decompose_prompt(prompt) to get a structured scaffold.\n"
            "3. Call forgecad_doc_topics(prompt), then forgecad_api_lookup(topic) for selected topics.\n"
            "4. Use forgecad_web_doc_lookup(topic) only if local lookup is missing a required API or compile repair needs it.\n"
            "5. Choose a short kebab-case design_name.\n"
            "6. Write one clean sequential ForgeCAD .forge.js script that returns the final renderable.\n"
            "7. Call forgecad_code_lint(js_content) and fix all lint errors before export.\n"
            "8. Prefer write_and_export_forgecad_model(design_name, js_content) to write and export in one step. IMPORTANT: This tool returns a JSON-serialized string! You MUST parse it to a dictionary using `import json; res_dict = json.loads(res)` before returning it to `FINAL({\"results\": [res_dict]})`.\n"
            "9. If compilation fails, print the error, use lookup/lint if needed, repair the .forge.js, and retry at most twice.\n"
            "10. Return the final validated structure matching schemas/cad_generation.py.\n"
        ),
    }
    # 3. Load Output Verification Schema
    schema_path_str = flags.get("schema")
    if schema_path_str:
        schema_path = Path(__file__).parent / schema_path_str
        print(f"[INFO] Loading verification schema from: {schema_path_str}")
        if schema_path.suffix == ".py":
            schema = load_pydantic_schema(schema_path)
        else:
            with open(schema_path) as f:
                schema = json.load(f)
    else:
        raise ValueError("Please specify a valid schema file path in run_cad.yaml")

    # 4. Load Tools
    tools = get_tools(flags.get("tools")) 

    # --- Prepend Routed ForgeCAD Skill Description to Payload ---
    skill_path_str = flags.get("skill")

    selected_skills = select_forgecad_skills(skill_path_str, custom_prompt)

    # Merge the contents of all selected skills
    merged_skill_content = ""
    for skill_file in selected_skills:
        skill_path = Path(__file__).parent / skill_file
        if skill_path.exists():
            if not _skill_is_forgecad_safe(skill_path):
                print(f"[WARN] Skipping unsafe skill with conflicting CAD APIs: {skill_file}")
                continue
            print(f"[INFO] Loading ForgeCAD skill rules from: {skill_file}")
            merged_skill_content += _read_text(skill_path).strip() + "\n\n"

    query = (
        f"{merged_skill_content.strip()}\n\n"
        "# CAD Generation Task\n\n"
        f"{payload['task_instructions']}"
    )

    print("Starting fast-rlm ForgeCAD run...")
    print(
        f"[INFO] Loaded {len(selected_skills)} compact skill file(s). "
        "ForgeCAD API docs are available through host lookup tools."
    )

    # 5. Call fast-rlm runner
    prefix = flags.get("prefix", "forgecad_generation")
    log_file = None
    
    mcp_python = sys.executable
    try:
        import mcp
    except ImportError:
        for candidate in ["/Users/makumar/.local/bin/python3", "python3", "python"]:
            try:
                import subprocess
                res = subprocess.run([candidate, "-c", "import mcp"], capture_output=True)
                if res.returncode == 0:
                    mcp_python = candidate
                    break
            except Exception:
                continue

    mcp_servers = {
        "host_tools": {
            "command": mcp_python,
            "args": [str(Path(__file__).parent / "tools" / "host_mcp.py")]
        }
    }

    try:
        result = fast_rlm.run(
            query=query,
            prefix=prefix,
            config=config,
            llm_kwargs=llm_kwargs or None,
            output_schema=schema,
            tools=tools,
            mcp_servers=mcp_servers,
            verbose=flags.get("verbose", True),
        )
        log_file = result.get("log_file")
        
        # Strict post-execution check: make sure results completed successfully and contain NO compile errors
        results_list = result.get("results", [])
        if isinstance(results_list, dict) and "results" in results_list:
            results_list = results_list["results"]
            
        for item in results_list:
            logs = item.get("compilation_logs", "").lower()
            if "error" in logs or "failed" in logs or "exit code" in logs:
                print("\n[ERROR] Airtight Safety Check Failed: The compilation logs contain error messages!")
                print(f"Error Logs:\n{item.get('compilation_logs')}")
                raise RuntimeError("CAD compilation failed! Please fix your script and re-run compilation.")
                
    except Exception as e:
        print(f"\n[ERROR] fast-rlm run failed: {e}")
        log_dir = Path(__file__).parent / "logs"
        if log_dir.exists():
            matching_files = list(log_dir.glob(f"{prefix}_*.jsonl"))
            if matching_files:
                latest_log = max(matching_files, key=lambda f: f.stat().st_mtime)
                log_file = str(latest_log)
        if log_file:
            print("\n" + "="*40)
            print("EXECUTION TRACE (BEFORE FAILURE)")
            print("="*40)
            try:
                render_trace(log_file)
            except Exception as trace_err:
                print(f"Failed to render trace: {trace_err}")
        raise e

    # 6. Render Results
    print("\n" + "="*40)
    print("RUN COMPLETED SUCCESSFULLY")
    print("="*40)
    print("Results:")
    print(result.get("results"))
    print("\nUsage Stats:")
    print(result.get("usage"))
    print(f"\nLog file saved to: {log_file}")

    if log_file and os.path.exists(log_file):
        print("\n" + "="*40)
        print("EXECUTION TRACE")
        print("="*40)
        try:
            render_trace(log_file)
        except Exception as trace_err:
            print(f"Failed to render trace: {trace_err}")

if __name__ == "__main__":
    main()
