import json
import re
from datetime import datetime, timezone

from backend.config import settings
from backend.security.path_guard import relative_path
from backend.utils.response import BridgeError

RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _trace_path(run_id: str):
    if not RUN_ID_RE.fullmatch(run_id):
        raise BridgeError("INVALID_REQUEST", "run_id may only contain letters, numbers, dot, dash, and underscore")
    return settings.traces_dir / f"{run_id}.jsonl"


def save_trace(run_id: str, event: dict) -> dict:
    path = _trace_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "step": event.get("step"),
        "event_type": event.get("event_type"),
        "tool_name": event.get("tool_name"),
        "input": event.get("input"),
        "output": event.get("output"),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
    return {"run_id": run_id, "trace_path": relative_path(path)}


def get_trace(run_id: str) -> dict:
    path = _trace_path(run_id)
    if not path.exists():
        raise BridgeError("TRACE_NOT_FOUND", f"Trace not found: {run_id}")
    events = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                events.append(json.loads(line))
    return {"run_id": run_id, "events": events}
