"""System diagnostics for the local UI control center."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from backend.services.temporal_manager import (
    LOGS,
    ensure_running,
    stop_worker,
)
from backend.services.temporal_manager import (
    status as temporal_status,
)

_LOG_FILES = {
    "temporal_worker": "temporal_worker.log",
    "temporal_server": "temporal_server.log",
}


def get_system_status() -> dict[str, object]:
    """Return local dependency and service status for the frontend."""
    return {
        "backend": {"status": "ok", "version": "0.1.0"},
        "temporal": temporal_status(),
        "tools": {
            "temporal_cli": shutil.which("temporal"),
            "forgecad_cli": shutil.which("forgecad"),
            "mypy": shutil.which("mypy"),
            "ruff": shutil.which("ruff"),
        },
        "config": {
            "forgecad_studio_url": os.environ.get("FORGECAD_STUDIO_URL", ""),
            "backend_url": os.environ.get("BACKEND_URL", ""),
        },
        "logs": sorted(_LOG_FILES),
    }


def read_log_tail(service: str, *, tail: int = 200) -> dict[str, object]:
    """Return a safe tail from a known local log file."""
    if service not in _LOG_FILES:
        raise KeyError(f"unknown log service {service!r}")
    line_count = max(1, min(tail, 1000))
    path = LOGS / _LOG_FILES[service]
    return {
        "service": service,
        "path": str(path),
        "lines": _tail_lines(path, line_count),
    }


def restart_temporal_worker() -> dict[str, object]:
    """Restart the backend-managed Temporal dev server and worker."""
    stop_worker()
    ok, message = ensure_running()
    current_status = temporal_status()
    current_status["ok"] = ok
    current_status["message"] = message
    return current_status


def _tail_lines(path: Path, line_count: int) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-line_count:]
    except OSError:
        return []
