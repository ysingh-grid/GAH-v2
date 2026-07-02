import json
import os
import urllib.error
import urllib.request
from typing import Any

DTCM_BACKEND_URL = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{DTCM_BACKEND_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode("utf-8"))


def list_skills() -> dict[str, Any]:
    return _post("/internal/list-skills", {})


def read_skill(skill_name: str) -> dict[str, Any]:
    return _post("/internal/read-skill", {"skill_name": skill_name})


def scan_repo(path: str = ".", max_depth: int = 4) -> dict[str, Any]:
    return _post("/internal/scan-repo", {"path": path, "max_depth": max_depth})


def read_file(path: str) -> dict[str, Any]:
    return _post("/internal/read-file", {"path": path})


def write_file(path: str, content: str, overwrite: bool = True) -> dict[str, Any]:
    return _post("/internal/write-file", {"path": path, "content": content, "overwrite": overwrite})


def list_dir(path: str = ".") -> dict[str, Any]:
    return _post("/internal/list-dir", {"path": path})


def run_pipeline(
    pipeline_name: str,
    args: dict[str, Any] | None = None,
    run_id: str | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    return _post(
        "/internal/run-pipeline",
        {
            "pipeline_name": pipeline_name,
            "args": args or {},
            "run_id": run_id,
            "timeout_seconds": timeout_seconds,
        },
    )


def execute_tool(tool_name: str, payload: dict[str, Any] | None = None, run_id: str | None = None) -> dict[str, Any]:
    return _post("/internal/execute-tool", {"tool_name": tool_name, "payload": payload or {}, "run_id": run_id})


def inspect_output(path: str, inspection_type: str = "file_metadata") -> dict[str, Any]:
    return _post("/internal/inspect-output", {"path": path, "inspection_type": inspection_type})


def save_trace(
    run_id: str,
    step: int,
    event_type: str,
    tool_name: str | None = None,
    input: Any = None,
    output: Any = None,
) -> dict[str, Any]:
    return _post(
        "/internal/save-trace",
        {
            "run_id": run_id,
            "step": step,
            "event_type": event_type,
            "tool_name": tool_name,
            "input": input,
            "output": output,
        },
    )


def get_trace(run_id: str) -> dict[str, Any]:
    return _post("/internal/get-trace", {"run_id": run_id})
