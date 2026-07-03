"""HTTP + WebSocket layer for the designs service. Thin handlers over store/runner."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.designs import store
from backend.designs.runner import run_chat_turn
from runtime.events import list_events

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_OUTPUTS_DIR = _REPO_ROOT / "artifacts"
_SESSIONS_DIR = _REPO_ROOT / "sessions"


# ── Session Config Model ──────────────────────────────────────────────────────


class SessionConfig(BaseModel):
    """Runtime toggles set by the UI sidebar switches."""
    use_temporal: bool = False
    use_forgecad: bool = False


# ── Session Config Endpoint ───────────────────────────────────────────────────


@router.post("/designs/{design_id}/config")
def update_session_config(design_id: str, config: SessionConfig) -> dict:
    """Update runtime toggles (Temporal, ForgeCAD) for a design session.

    Toggles take effect on the NEXT run — you can't switch engines mid-pipeline.
    """
    try:
        session = store.get_session(design_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session.use_temporal = config.use_temporal
    session.use_forgecad = config.use_forgecad
    return {"design_id": design_id, "config": config.model_dump()}


# ── Session Lifecycle ─────────────────────────────────────────────────────────


@router.post("/designs", status_code=201)
def create_design() -> dict:
    """Create a new design chat session. Returns its id."""
    session = store.create_session()
    return {"design_id": session.id}


@router.get("/designs/{design_id}")
def get_design(design_id: str) -> dict:
    """Return current state of a design session (id, status, history, …)."""
    try:
        session = store.get_session(design_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return session.to_dict()


@router.websocket("/designs/{design_id}/chat")
async def chat_ws(design_id: str, ws: WebSocket) -> None:
    """Stream chat turns over WebSocket.

    Client → Server:  {"type": "message", "text": str}
    Server → Client:  typed events — see runner.py docstring for full list.

    Connection closes automatically after a terminal event (success / failed).
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

            if session.status in ("done", "failed"):
                await ws.close()
                break

    except WebSocketDisconnect:
        pass


# ── Run History Endpoints ────────────────────────────────────────────────────


@router.get("/runs")
def list_runs() -> list[dict]:
    """List all past runs: active sessions + completed traces from disk.

    Merges in-memory DesignSessions with trace files from outputs/ and
    session snapshots from sessions/. Returns ids, prompts, statuses, and
    artifact paths where available.
    """
    runs: list[dict] = []

    # 1. Active in-memory sessions (chatting / generating / needs_user)
    for sid, session in store._sessions.items():
        runs.append({
            "run_id": session.run_id or sid,
            "design_id": sid,
            "prompt": session.original_prompt or "",
            "status": session.status,
            "source": "memory",
        })

    # 2. Completed traces from outputs/ (each folder with a trace.json)
    if _OUTPUTS_DIR.exists():
        for d in sorted(os.listdir(_OUTPUTS_DIR)):
            artifact_dir = _OUTPUTS_DIR / d
            if not artifact_dir.is_dir():
                continue
            trace_path = artifact_dir / "trace.json"
            if not trace_path.exists():
                has_stl = (artifact_dir / "solid.stl").exists()
                has_step = (artifact_dir / "solid.step").exists()
                has_render = (artifact_dir / "threeview.png").exists()
                if not (has_stl or has_step or has_render):
                    continue
                runs.append({
                    "run_id": d,
                    "design_id": d,
                    "prompt": "",
                    "status": "incomplete",
                    "timestamp": "",
                    "has_stl": has_stl,
                    "has_step": has_step,
                    "has_render": has_render,
                    "has_events": (artifact_dir / "events.jsonl").exists(),
                    "has_trace": False,
                    "source": "outputs",
                })
                continue
            try:
                trace = json.loads(trace_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            runs.append({
                "run_id": d,
                "design_id": d,
                "prompt": trace.get("prompt", ""),
                "status": trace.get("outcome", {}).get("status", "unknown"),
                "timestamp": trace.get("timestamp", ""),
                "has_stl": (_OUTPUTS_DIR / d / "solid.stl").exists(),
                "has_step": (_OUTPUTS_DIR / d / "solid.step").exists(),
                "has_events": (_OUTPUTS_DIR / d / "events.jsonl").exists(),
                "has_trace": True,
                "source": "outputs",
            })

    # 3. Session snapshots from sessions/ (persisted JSON)
    if _SESSIONS_DIR.exists():
        for f in sorted(os.listdir(_SESSIONS_DIR)):
            if not f.endswith(".json") or f == "latest.txt":
                continue
            try:
                snap = json.loads((_SESSIONS_DIR / f).read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            runs.append({
                "run_id": snap.get("run_id", f.replace(".json", "")),
                "design_id": snap.get("design_id", ""),
                "prompt": snap.get("original_prompt", ""),
                "status": snap.get("status", "unknown"),
                "timestamp": snap.get("timestamp", ""),
                "source": "sessions",
            })

    # Deduplicate by run_id (prefer memory > outputs > sessions)
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in runs:
        rid = r["run_id"]
        if rid in seen:
            continue
        seen.add(rid)
        deduped.append(r)

    # Sort: most recent first
    deduped.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return deduped


@router.get("/runs/{run_id}/trace")
def get_run_trace(run_id: str) -> dict:
    """Return the full trace JSON for a completed run."""
    trace_path = _OUTPUTS_DIR / run_id / "trace.json"
    if not trace_path.exists():
        session_path = _SESSIONS_DIR / f"{run_id}.json"
        if session_path.exists():
            try:
                return json.loads(session_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        raise HTTPException(status_code=404, detail=f"no trace found for run_id {run_id!r}")
    return json.loads(trace_path.read_text(encoding="utf-8"))


@router.get("/runs/{run_id}/events")
def get_run_events(run_id: str) -> dict:
    """Return the normalized timeline events for a run."""
    return {"run_id": run_id, "events": list_events(run_id)}


@router.get("/runs/{run_id}/artifacts")
def get_run_artifacts(run_id: str) -> dict:
    """Return artifact availability for a run without reading heavy files."""
    artifact_dir = _OUTPUTS_DIR / run_id
    if not artifact_dir.exists():
        raise HTTPException(status_code=404, detail=f"no artifacts found for run_id {run_id!r}")
    return {
        "run_id": run_id,
        "has_events": (artifact_dir / "events.jsonl").exists(),
        "has_trace": (artifact_dir / "trace.json").exists(),
        "has_stl": (artifact_dir / "solid.stl").exists()
        or (artifact_dir / "solid_repaired.stl").exists(),
        "has_step": (artifact_dir / "solid.step").exists(),
        "has_render": (artifact_dir / "threeview.png").exists(),
        "forgecad_preview": (_OUTPUTS_DIR / "forgecad" / "main.forge.js").exists(),
    }


@router.get("/runs/{run_id}/stl")
def get_run_stl(run_id: str) -> FileResponse:
    """Download the STL file for a completed run."""
    stl_path = _OUTPUTS_DIR / run_id / "solid.stl"
    if not stl_path.exists():
        repaired = _OUTPUTS_DIR / run_id / "solid_repaired.stl"
        if repaired.exists():
            stl_path = repaired
        else:
            raise HTTPException(status_code=404, detail=f"no STL found for run_id {run_id!r}")
    return FileResponse(
        path=str(stl_path),
        media_type="application/sla",
        filename=f"{run_id}.stl",
    )


@router.get("/runs/{run_id}/step")
def get_run_step(run_id: str) -> FileResponse:
    """Download the STEP file for a completed run."""
    step_path = _OUTPUTS_DIR / run_id / "solid.step"
    if not step_path.exists():
        raise HTTPException(status_code=404, detail=f"no STEP found for run_id {run_id!r}")
    return FileResponse(
        path=str(step_path),
        media_type="application/step",
        filename=f"{run_id}.step",
    )
