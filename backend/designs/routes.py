"""HTTP + WebSocket layer for the designs service. Thin handlers over store/runner."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from backend.designs import store
from backend.designs.runner import run_chat_turn

router = APIRouter()


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
