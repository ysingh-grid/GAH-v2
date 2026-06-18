"""
rlm.py — Entrypoint to run fast-rlm.

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

# ==========================================
# 1. Credentials & Endpoint Setup
# ==========================================
# Ensure required environment variables are set before running
if not os.environ.get("RLM_MODEL_API_KEY"):
    raise RuntimeError("RLM_MODEL_API_KEY is missing. Please set it in your .env file.")

# Intelligent endpoint router:
# If using a Google Gemini key (which begins with "AIzaSy"), automatically use the Google AI Studio endpoint.
# Otherwise, fall back to the defaults (OpenRouter, OpenAI, etc.).
api_key = os.environ.get("RLM_MODEL_API_KEY", "")
if api_key.startswith("AIzaSy"):
    os.environ["RLM_MODEL_BASE_URL"] = "https://generativelanguage.googleapis.com/v1beta/openai"
    print(f"[INFO] Google Gemini API Key detected. Using endpoint: {os.environ['RLM_MODEL_BASE_URL']}")

# ==========================================
# 2. Main Execution
# ==========================================
DEFAULT_CONFIG_PATH = Path(__file__).parent / "run.yaml"


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
    module_name = path.stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from spec at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    from pydantic import BaseModel
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and issubclass(attr, BaseModel) and attr is not BaseModel:
            # Wrap the found BaseModel in list[...] since the output is expected to be a list
            return list[attr]
    raise ValueError(f"No Pydantic BaseModel subclass found in {path}")


def main():

    # ==========================================
    # 3. Load Configurations
    # ==========================================
    config, llm_kwargs, flags = load_run_config()

    payload = {
        "role_instructions": "",
        "task_instructions": (
            "Follow guidelines: 1. Call mcp_list_tools() for tool. 2. Read 'todos.txt' for rules, analyze 5 fruits (at least 2 >=8 chars), return schema with 'mcp_tools_used' and 'file_preview' (2 lines)."
        ),
        "workflow": [
            {
                "step": 1,
                "description": "Generate a list of 5 common fruits. Return the validated output structure.",
                "schema": {
                    "type": "object",
                    "properties": {
                        "fruits": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["fruits"]
                }
            }
        ]
    }

    # ==========================================
    # 4. Load Output Verification Schema
    # ==========================================
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
        # Fallback to the default hardcoded schema if no file is specified
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fruit": {"type": "string", "description": "The name of the fruit"},
                    "a_count": {"type": "integer", "description": "Number of 'a's in the name"},
                    "name_length": {"type": "integer", "description": "Character length of the name"},
                    "vowel_count": {"type": ["integer", "null"], "description": "The number of vowels, calculated using the tool only if name_length >= 8, otherwise NONE"},
                    "tools_used": {"type": "object", "description": "A dictionary mapping the purpose of the call to the name of the tool function executed"},
                },
                "required": ["fruit", "a_count", "name_length", "vowel_count", "tools_used"],
            }
        }

    # ==========================================
    # 5. Load Tools
    # ==========================================
    tools = get_tools(flags.get("tools")) 

    # --- Prepend Skill Description to Payload ---
    query = payload
    skill_path_str = flags.get("skill")
    if skill_path_str:
        skill_path = Path(__file__).parent / skill_path_str
        if skill_path.exists():
            print(f"[INFO] Loading skill rules from: {skill_path_str}")
            with open(skill_path) as f:
                skill_content = f.read()
            query["role_instructions"] = skill_content.strip()

    print("Starting fast-rlm run...")
    print(f"Payload: {payload}\n")

    # ==========================================
    # 6. Call fast-rlm runner
    # ==========================================
    prefix = flags.get("prefix", "fruit_analysis")
    log_file = None
    
    # Find a python interpreter that has 'mcp' installed for our host MCP server
    mcp_python = sys.executable
    try:
        import mcp
    except ImportError:
        # If current virtualenv doesn't have mcp, check standard system paths
        for candidate in ["/Users/makumar/.local/bin/python3", "python3", "python"]:
            try:
                import subprocess
                res = subprocess.run([candidate, "-c", "import mcp"], capture_output=True)
                if res.returncode == 0:
                    mcp_python = candidate
                    break
            except Exception:
                continue

    # Configure host-level MCP servers to bypass WASM/Pyodide environment restrictions
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
    except Exception as e:
        print(f"\n[ERROR] fast-rlm run failed: {e}")
        # Try to find the latest log file matching the prefix to render trace for debugging
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

    # ==========================================
    # 7. Render Results
    # ==========================================
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
