"""
orchestrator_translate.py — Dedicated compiler entrypoint to translate CadQuery code to ForgeCAD.

Usage:
  python orchestrator_translate.py <path_to_cadquery_script.py>
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


def load_run_config(path=DEFAULT_CONFIG_PATH):
    cfg = yaml.safe_load(open(path)) or {}
    config = {k: v for k, v in cfg.items() if k in CONFIG_KEYS and v is not None}
    llm_kwargs = {k: v for k, v in cfg.items() if k in LLM_KEYS and v is not None}
    flags = {k: v for k, v in cfg.items()
             if k not in CONFIG_KEYS and k not in LLM_KEYS and v is not None}
    return config, llm_kwargs, flags


def load_pydantic_schema(path: Path):
    """Dynamically load a Pydantic model from a Python file path."""
    module_name = path.get("stem") if hasattr(path, "get") else path.stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from spec at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # If CADGenerationContainer is defined in the module, use it directly
    container = getattr(module, "CADGenerationContainer", None)
    if container:
        print("[INFO] Using CADGenerationContainer schema with strict min_length=1 array validation.")
        return container

    from pydantic import BaseModel
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and issubclass(attr, BaseModel) and attr is not BaseModel:
            return list[attr]
    raise ValueError(f"No Pydantic BaseModel subclass found in {path}")


def _read_text(path: Path) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def main():
    # 1. Load Configurations
    config_path = DEFAULT_CONFIG_PATH
    
    if len(sys.argv) < 2:
        print("[ERROR] Please provide the path to a Python CadQuery script to translate.")
        print("Usage: python orchestrator_translate.py <path_to_script.py>")
        sys.exit(1)

    cq_script_path = Path(sys.argv[1])
    if not cq_script_path.exists():
        print(f"[ERROR] Specified CadQuery script does not exist: {cq_script_path}")
        sys.exit(1)

    print(f"[INFO] Loading CadQuery script to translate: {cq_script_path}")
    cq_code = _read_text(cq_script_path)

    config, llm_kwargs, flags = load_run_config(config_path)

    # 2. Define payload for the translation task
    payload = {
        "role_instructions": "",
        "task_instructions": (
            "You are a specialized compiler agent. Your task is to translate the following "
            "Python CadQuery script into clean, compile-ready, and parametric ForgeCAD JavaScript.\n\n"
            "--- START CADQUERY CODE ---\n"
            f"{cq_code}\n"
            "--- END CADQUERY CODE ---\n\n"
            "Hard constraints:\n"
            "- Generate ForgeCAD JavaScript only.\n"
            "- Never use CadQuery, Python CAD code, OpenSCAD, JSCAD, CSG, or @jscad/modeling inside the final Javascript script.\n"
            "- Never guess, invent, or assume any API names or signatures. If you are not 100% certain of a function's name or exact parameter ordering, you MUST use 'forgecad_api_lookup(symbol)' or 'forgecad_web_doc_lookup(topic)' to verify it in the reference codebase before writing it!\n"
            "- Do not create scratch output folders.\n"
            "- Do not use silent try/catch fallbacks.\n"
            "- Do not inspect or print full context, docs, schema, or role instructions.\n\n"
            "Terminal trace requirements:\n"
            "- Before each major action, print 'Step:', 'Reasoning summary:', and 'Next action:'.\n"
            "- Print the tool name and compact arguments before each tool call.\n"
            "- Print tool output summaries and full compiler/export errors.\n"
            "- Do not print hidden chain-of-thought; use concise visible reasoning summaries only.\n\n"
            "Required workflow:\n"
            "1. Discover host tools using mcp_list_tools().\n"
            "2. Analyze the input CadQuery code and plan how to map its stateful workplane logic to ForgeCAD absolute CSG.\n"
            "3. Select a short kebab-case design_name.\n"
            "4. If you are unsure of any API signatures, call forgecad_api_lookup(symbol) first to verify them. NEVER GUESS.\n"
            "5. Write one clean sequential ForgeCAD .forge.js script that returns the final shape or grouped assembly.\n"
            "6. Call forgecad_code_lint(js_content) and resolve all lint issues before compilation.\n"
            "7. Compile and export the model using write_and_export_forgecad_model(design_name, js_content).\n"
            "8. If compilation fails, analyze the error logs, repair the code, and re-export.\n"
            "9. Return the final successfully compiled result matching schemas/cad_generation.py.\n"
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

    # --- Prepend Core Skills and Translation Skill ---
    selected_skills = [
        "skills/forgecad_designer.md",
        "skills/forgecad_runtime_core.md",
        "skills/forgecad_doc_index.md",
        "skills/forgecad_translator.md",
    ]

    merged_skill_content = ""
    for skill_file in selected_skills:
        skill_path = Path(__file__).parent / skill_file
        if skill_path.exists():
            print(f"[INFO] Loading ForgeCAD skill rules from: {skill_file}")
            merged_skill_content += _read_text(skill_path).strip() + "\n\n"

    query = (
        f"{merged_skill_content.strip()}\n\n"
        "# CAD Translation Task\n\n"
        f"{payload['task_instructions']}"
    )

    print("Starting fast-rlm ForgeCAD Translation run...")
    print(
        f"[INFO] Loaded {len(selected_skills)} compact skill file(s). "
        "ForgeCAD API docs are available through host lookup tools."
    )

    # 5. Call fast-rlm runner
    prefix = "forgecad_translation"
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
