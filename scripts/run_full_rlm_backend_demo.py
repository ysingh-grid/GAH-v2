import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import fast_rlm
from rlm.rlm_config import config
from tools.backend_bridge import BACKEND_BRIDGE_TOOLS


def load_env_file(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> None:
    load_env_file(PROJECT_ROOT / ".env")

    if not os.getenv("GEMINI_API_KEY"):
        raise SystemExit(
            "GEMINI_API_KEY is not set. Add it to .env or export it, then rerun:\n"
            "  python scripts/run_full_rlm_backend_demo.py"
        )

    task = """
You are the actual fast_rlm runtime testing the backend bridge and using the
project skills/tools to plan a CAD workflow.

Use only the provided backend_* tools. Do not assume direct filesystem access.
Every backend tool returns an ApiResponse dictionary with this shape:
{"ok": bool, "tool": str, "data": ..., "error": ..., "run_id": ..., "trace_id": ...}
Always read values from response["data"]. Do not slice or index the whole
response as if it is a list or raw string.

Do these exact steps:
1. Call backend_build_skill_tool_report with run_id "rlm_full_demo".
2. Read report = response["data"].
3. Return FINAL with exactly these lines:
   Backend URL: <report["backend_url"]>
   Skill names seen: <comma-separated report["skill_names"]>
   Skills loaded and used: <comma-separated report["loaded_skills"]>
   Primitive tools used: <comma-separated report["selected_primitives"]>
   Repo file count: <report["repo_file_count"]>
   Generated report path: <report["generated_report_path"]>

Do not call inspect.getsource. Do not inspect os.environ. Use backend_health for backend URL/status.
Do not recompute repo_file_count yourself. Do not print raw dictionaries in FINAL.
"""

    print("Starting actual fast_rlm run with backend bridge tools")
    print(f"Backend URL: {os.getenv('DTCM_BACKEND_URL', 'http://localhost:8001')}")
    print(f"Tools exposed to RLM: {[tool.__name__ for tool in BACKEND_BRIDGE_TOOLS]}")

    result = fast_rlm.run(
        task,
        config=config,
        tools=BACKEND_BRIDGE_TOOLS,
        env_variables={"DTCM_BACKEND_URL": os.getenv("DTCM_BACKEND_URL", "http://localhost:8001")},
        verbose=True,
    )

    print("\nFAST_RLM_RESULT")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
