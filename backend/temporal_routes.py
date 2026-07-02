"""HTTP endpoints for Temporal service lifecycle management.

POST /temporal/start  → start server + worker (idempotent)
POST /temporal/stop   → stop the worker
GET  /temporal/status → check current state
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.services import ensure_running, status, stop_worker

router = APIRouter(prefix="/temporal", tags=["temporal"])


@router.post("/start")
def start_temporal() -> dict:
    """Start the Temporal server and worker.

    Idempotent — if already running, just reports status.
    Blocks for up to ~12 s if the server needs to cold-start.
    """
    return ensure_running()


@router.post("/stop")
def stop_temporal() -> dict:
    """Stop the Temporal worker subprocess.

    The server stays up (it's lightweight and may have other uses),
    but no workflows will be picked up until the worker is restarted.
    """
    stop_worker()
    return status()


@router.get("/status")
def get_temporal_status() -> dict:
    """Return current Temporal services health."""
    return status()