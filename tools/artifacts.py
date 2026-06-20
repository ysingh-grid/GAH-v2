"""Run-scoped artifact paths. One folder per run: outputs/{run_id}/.

Every writer tool (execute_cadquery, render_views, write_trace) asks THIS module
where to write, instead of each recomputing the repo root. Single source of truth
for "where do artifacts live" — swap outputs/ for blob storage later by editing
only this file. This is the MVP stand-in for the PRD "artifact store".
"""
from pathlib import Path
from datetime import datetime, timezone
import uuid

# this file = <repo>/tools/artifacts.py  ->  parent.parent = repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent
_OUTPUTS = _REPO_ROOT / "outputs"


def new_run_id(label: str | None = None) -> str:
    """Sortable, unique run id: '20260619-153012_a1b2'.

    UTC timestamp (so `ls` sorts chronologically) + 4 hex chars (collision guard).
    Pass `label` to prefix it, e.g. new_run_id("manual") -> 'manual_20260619-153012_a1b2'.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    short = uuid.uuid4().hex[:4]
    base = f"{ts}_{short}"
    return f"{label}_{base}" if label else base


def run_dir(run_id: str) -> Path:
    """Return (and create) outputs/{run_id}/ — the folder owning ALL artifacts for this run."""
    d = _OUTPUTS / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d
