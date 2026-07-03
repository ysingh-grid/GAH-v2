"""Normalized per-run event timeline stored under artifacts/{run_id}/events.jsonl."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.artifacts import run_dir

_SCHEMA_VERSION = 1
_TEXT_LIMIT = 4000


def append_event(
    run_id: str,
    *,
    source: str,
    stage: str,
    status: str,
    title: str,
    summary: str = "",
    payload: dict[str, Any] | None = None,
    artifact_refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one normalized timeline event and return the event payload."""
    path = _events_path(run_id)
    event = {
        "schema_version": _SCHEMA_VERSION,
        "run_id": run_id,
        "seq": _next_sequence(path),
        "time": datetime.now(UTC).isoformat(),
        "source": source,
        "stage": stage,
        "status": status,
        "title": title,
        "summary": summary,
        "payload": payload or {},
        "artifact_refs": artifact_refs or {},
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def list_events(run_id: str) -> list[dict[str, Any]]:
    """Read normalized events for a run. Missing timelines return an empty list."""
    path = _events_path(run_id)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    return events


def ingest_rlm_log(run_id: str, log_file: str, *, stage: str) -> list[dict[str, Any]]:
    """Convert a fast-RLM JSONL log into normalized UI timeline events."""
    log_path = Path(log_file)
    events = [
        append_event(
            run_id,
            source="rlm",
            stage=stage,
            status="info",
            title="RLM log captured",
            summary=log_path.name,
            artifact_refs={"rlm_log": str(log_path)},
        )
    ]
    if not log_path.exists():
        return events

    for row in _read_jsonl(log_path):
        event = _event_from_rlm_row(run_id, stage, row)
        if event is not None:
            events.append(event)
    return events


def _events_path(run_id: str) -> Path:
    return run_dir(run_id) / "events.jsonl"


def _next_sequence(path: Path) -> int:
    if not path.exists():
        return 1
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()) + 1


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"event_type": "log_parse_error", "raw": _truncate(line)})
    return rows


def _event_from_rlm_row(
    run_id: str,
    stage: str,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    event_type = str(row.get("event_type") or "unknown")
    status = "error" if row.get("hasError") else "ok"

    if event_type == "agent_start":
        return append_event(
            run_id,
            source="rlm",
            stage=stage,
            status="running",
            title="RLM agent started",
            summary=f"depth={row.get('depth', 0)}",
            payload=_compact_row(row),
        )
    if event_type == "agent_end":
        return append_event(
            run_id,
            source="rlm",
            stage=stage,
            status="ok",
            title="RLM agent finished",
            payload=_compact_row(row),
        )
    if event_type == "code_generated":
        return append_event(
            run_id,
            source="rlm",
            stage=stage,
            status="running",
            title="RLM generated code",
            summary=_first_line(row.get("code", "")),
            payload=_compact_row(row),
        )
    if event_type == "execution_result":
        title = "RLM execution failed" if row.get("hasError") else "RLM executed step"
        return append_event(
            run_id,
            source="rlm",
            stage=stage,
            status=status,
            title=title,
            summary=_first_line(row.get("output", "")),
            payload=_compact_row(row),
        )
    if event_type == "final_result":
        return append_event(
            run_id,
            source="rlm",
            stage=stage,
            status="ok",
            title="RLM final result",
            summary=_summarize_result(row.get("result")),
            payload=_compact_row(row),
        )
    return None


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    compact = dict(row)
    for key in ("code", "output"):
        if key in compact:
            text = str(compact[key])
            compact[key] = _truncate(text)
            compact[f"{key}_truncated"] = len(text) > _TEXT_LIMIT
    return compact


def _truncate(text: str) -> str:
    if len(text) <= _TEXT_LIMIT:
        return text
    return text[:_TEXT_LIMIT] + "\n...[truncated]"


def _first_line(value: object) -> str:
    text = str(value or "").strip()
    return _truncate(text.splitlines()[0] if text else "")


def _summarize_result(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("part_name") or value.get("status") or "structured result")
    return _first_line(value)
