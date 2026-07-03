"""System diagnostics and local lifecycle controls for the UI."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.services.system_diagnostics import (
    get_system_status,
    read_log_tail,
    restart_temporal_worker,
)

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status")
def get_status() -> dict[str, object]:
    """Return backend, Temporal, tool, config, and log availability."""
    return get_system_status()


@router.get("/logs")
def get_logs(service: str, tail: int = 200) -> dict[str, object]:
    """Return the tail of a known service log."""
    try:
        return read_log_tail(service, tail=tail)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/restart-worker")
def post_restart_worker() -> dict[str, object]:
    """Restart the backend-managed Temporal worker."""
    return restart_temporal_worker()
