"""Read-only reader for previous design runs (the UI's 'Previous Run' list).

A read-only door onto the on-disk artifact store: it scans
``outputs/{run_id}/trace.json`` and returns compact, newest-first run
summaries. It holds no session state and mutates nothing — mirroring the
``*_read`` service convention used elsewhere in ``backend/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# this file = <repo>/backend/designs/history.py -> parents[2] = repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUTPUTS = _REPO_ROOT / "outputs"


def _summarize_trace(trace: dict[str, Any]) -> dict[str, Any]:
    """Extract the compact summary the run picker needs from a full trace."""
    outcome = trace.get("outcome") or {}
    plan = trace.get("plan") or {}
    prompt = str(trace.get("prompt") or "")
    return {
        "run_id": trace.get("run_id", ""),
        "timestamp": trace.get("timestamp", ""),
        "prompt": prompt.split("\n", 1)[0][:120],  # first line only, capped
        "part_name": plan.get("part_name", ""),
        "status": outcome.get("status", "unknown"),
        "failure_category": outcome.get("failure_category"),
    }


def list_previous_runs(outputs_dir: Path | None = None) -> list[dict[str, Any]]:
    """Return compact summaries of all persisted runs, newest-first.

    A run = any ``outputs/{run_id}/`` folder holding a ``trace.json``. Malformed
    or unreadable traces are skipped so a single bad file never breaks the list.
    Sorted by ``timestamp`` descending, with ``run_id`` as a stable tiebreaker.

    Args:
        outputs_dir: artifact-store root to scan; defaults to the repo ``outputs/``.
    """
    base = outputs_dir or _OUTPUTS
    if not base.exists():
        return []

    runs: list[dict[str, Any]] = []
    for child in base.iterdir():
        trace_path = child / "trace.json"
        if not (child.is_dir() and trace_path.exists()):
            continue
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        runs.append(_summarize_trace(trace))

    runs.sort(key=lambda r: (r.get("timestamp") or "", r.get("run_id") or ""), reverse=True)
    return runs
