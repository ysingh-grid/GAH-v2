"""HTTP + WebSocket layer for the designs service. Thin handlers over store/runner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from backend.designs import store
from backend.designs.history import list_previous_runs
from backend.designs.runner import cancel_run, run_chat_turn, write_stl_to_studio
from tools.load_trace import load_trace

router = APIRouter()

# Repo-root outputs/ dir — one folder per run holds trace.json + renders + STL/STEP.
_OUTPUTS = Path(__file__).resolve().parents[2] / "outputs"


@router.post("/designs", status_code=201)
def create_design() -> dict:
    """Create a new design chat session. Returns its id."""
    session = store.create_session()
    return {"design_id": session.id}


@router.get("/designs")
def list_designs() -> list[dict[str, Any]]:
    """List previous runs (newest first) for the UI's 'Previous Run' picker."""
    return list_previous_runs()


@router.get("/designs/{design_id}")
def get_design(design_id: str) -> dict:
    """Return current state of a design session (id, status, history, …)."""
    try:
        session = store.get_session(design_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return session.to_dict()


@router.get("/designs/{run_id}/trace")
def get_run_trace(run_id: str) -> dict[str, Any]:
    """Step-by-step record for the Logs panel: plan, CadQuery code, mesh, verdict, outcome."""
    result = load_trace(run_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "trace not found"))
    return result["trace"]


@router.get("/designs/{run_id}/artifacts")
def list_run_artifacts(run_id: str) -> dict[str, Any]:
    """URLs for a run's renders / STL / STEP (Render gallery + Previous-Run detail + downloads)."""
    base = _OUTPUTS / run_id
    if not base.is_dir():
        raise HTTPException(status_code=404, detail=f"no artifacts for run {run_id!r}")

    def urls(pattern: str) -> list[str]:
        return sorted(f"/outputs/{run_id}/{p.name}" for p in base.glob(pattern))

    return {
        "run_id": run_id,
        "renders": urls("*.png"),
        "stl": urls("*.stl"),
        "step": urls("*.step"),
    }


@router.post("/designs/{design_id}/cancel")
async def cancel_design(design_id: str) -> dict[str, Any]:
    """Cancel an in-flight run. Temporal workflows cancel cleanly; in-process
    runs are best-effort (the flag is set, but a stage already running finishes)."""
    try:
        session = store.get_session(design_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await cancel_run(session)


@router.post("/designs/{design_id}/handoff")
def handoff_design(design_id: str) -> dict[str, Any]:
    """Re-render the run's STL into the ForgeCAD Studio workspace.

    Gated on a finished, successful run — 400 if there is no completed run to
    hand off yet. Backs the UI's 'Handoff to ForgeCAD' button, which stays
    disabled until a success event arrives.
    """
    try:
        session = store.get_session(design_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if session.status != "done" or not session.run_id:
        raise HTTPException(
            status_code=400,
            detail="no successful run to hand off — generate a design first",
        )

    ok = write_stl_to_studio(session.run_id)
    return {"status": "handed_off" if ok else "failed", "run_id": session.run_id}


@router.websocket("/designs/{design_id}/chat")
async def chat_ws(design_id: str, ws: WebSocket) -> None:
    """Stream chat turns over WebSocket.

    Client → Server:  {"type": "message", "text": str}
    Server → Client:  typed events — see runner.py docstring for full list.

    The connection stays open after success/failed — the session isn't reset;
    the next message is a post-design question or edit request (see
    runner.run_chat_turn). Only a real client disconnect or design-not-found
    closes the socket.
    """
    await ws.accept()

    try:
        session = store.get_session(design_id)
    except KeyError:
        await ws.send_json({"type": "error", "message": f"design {design_id!r} not found"})
        await ws.close(code=1008)
        return

    async def send(event: dict) -> None:
        await ws.send_json(event)

    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") != "message":
                continue
            user_text = str(data.get("text", "")).strip()
            if not user_text:
                continue
            attachments = data.get("attachments")

            await run_chat_turn(session, user_text, send, attachments=attachments)

    except WebSocketDisconnect:
        pass
