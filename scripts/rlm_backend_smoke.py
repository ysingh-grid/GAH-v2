import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from rlm import tools


RUN_ID = "rlm_backend_smoke"


def require_ok(label: str, response: dict) -> dict:
    status = "ok" if response.get("ok") else response.get("error", {}).get("code", "failed")
    print(f"{label}: {status}")
    if not response.get("ok"):
        raise SystemExit(json.dumps(response, indent=2))
    return response["data"]


def require_error(label: str, response: dict, code: str) -> None:
    actual = response.get("error", {}).get("code")
    print(f"{label}: {actual}")
    if response.get("ok") or actual != code:
        raise SystemExit(json.dumps(response, indent=2))


def main() -> None:
    print(f"Backend URL: {tools.DTCM_BACKEND_URL}")
    print("Testing through rlm/tools.py only")

    skills = require_ok("list_skills", tools.list_skills())
    print("  skills:", ", ".join(skill["name"] for skill in skills["skills"]))

    intent = require_ok("read_skill intent_extraction", tools.read_skill("intent_extraction"))
    print("  intent_extraction chars:", len(intent["content"]))

    repo = require_ok("scan_repo", tools.scan_repo(".", max_depth=2))
    print("  repo files:", len(repo["files"]))
    print("  repo dirs:", len(repo["directories"]))

    skill_dir = require_ok("list_dir skills", tools.list_dir("skills"))
    print("  skill dir items:", len(skill_dir["items"]))

    payload = {
        "run_id": RUN_ID,
        "source": "rlm/tools.py",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "observed_skill_count": len(skills["skills"]),
        "observed_repo_file_count": len(repo["files"]),
    }
    written = require_ok(
        "write_file generated probe",
        tools.write_file("generated/rlm_backend_probe.json", json.dumps(payload, indent=2) + "\n"),
    )
    print("  wrote:", written["path"])

    summary = require_ok(
        "inspect_output json_summary",
        tools.inspect_output("generated/rlm_backend_probe.json", "json_summary"),
    )
    print("  json keys:", ", ".join(summary["summary"].get("top_level_keys", [])))

    require_ok("run_pipeline noop", tools.run_pipeline("noop", run_id=RUN_ID))
    require_ok("run_pipeline repo_check", tools.run_pipeline("repo_check", run_id=RUN_ID))

    echo = require_ok("execute_tool echo", tools.execute_tool("echo", {"message": "hello from rlm"}, run_id=RUN_ID))
    print("  echo result:", echo["result"]["echo"]["message"])

    require_error("blocked read_file .env", tools.read_file(".env"), "PATH_NOT_ALLOWED")

    require_ok(
        "save_trace",
        tools.save_trace(
            RUN_ID,
            step=1,
            event_type="smoke_test",
            tool_name="rlm_backend_smoke",
            input={"backend_url": tools.DTCM_BACKEND_URL},
            output={"status": "complete"},
        ),
    )
    trace = require_ok("get_trace", tools.get_trace(RUN_ID))
    print("  trace events:", len(trace["events"]))

    print("RLM backend bridge smoke test complete")


if __name__ == "__main__":
    main()
