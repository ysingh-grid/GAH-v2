"""HTTP endpoints for Temporal service lifecycle management.

POST /temporal/start  → start server + worker (idempotent)
POST /temporal/stop   → stop the worker
GET  /temporal/status → check current state
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.services.temporal_manager import ensure_running, status, stop_worker

router = APIRouter(prefix="/temporal", tags=["temporal"])


@router.post("/start")
def post_temporal_start() -> dict:
    """Start the Temporal dev server and python worker if not running."""
    ok, msg = ensure_running()
    st = status()
    st["message"] = msg
    return st


@router.post("/stop")
def post_temporal_stop() -> dict:
    """Stop the Temporal python worker (and dev server).
    
    Any active Temporal workflows will be picked up until the worker is restarted.
    """
    stop_worker()
    return status()


@router.get("/status")
def get_temporal_status() -> dict:
    """Return current Temporal services health."""
    return status()