"""Chat-turn orchestrator: planner → geometry loop → Studio render.

One async function (`run_chat_turn`) drives the full pipeline for a single user
message. Blocking work (RLM call, geometry loop) is dispatched to a thread-pool
executor so the event loop stays free for WS I/O.

Event protocol (Server → Client, JSON):
  {"type": "thinking"}                            — planner is working
  {"type": "generating", "stage"}                 — geometry loop running
  {"type": "success", "run_id", "plan"}           — part produced; Studio renders STL
  {"type": "failed", "category", "message"}       — exhausted / permanent error
  {"type": "error", "message"}                    — unexpected exception

The planner/replanner never ask the user a clarifying question — they always
resolve ambiguity themselves and return a plan, or the turn fails outright.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from backend.designs.intake import (
    IntakeOutcome,
    build_planner_history,
    parse_incoming_attachments,
    start_or_resume_intake,
)
from backend.designs.models import DesignSession
from runtime.events import append_event, list_events
from runtime.loop import LoopResult, run_geometry_loop
from runtime.planner import run_planner_turn, run_replanner_turn
from runtime.schema import PrimitivePlan, load_library, plan_to_dict
from tools.artifacts import new_run_id

log = logging.getLogger(__name__)

# Absolute path to the ForgeCAD Studio workspace (mounted at /workspace in the
# forgecad-studio container, bound to ./artifacts/forgecad on the host).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FORGECAD_WORKSPACE = _REPO_ROOT / "artifacts" / "forgecad"

_BACKEND_URL_DEFAULT = os.environ.get("BACKEND_URL", "http://localhost:8001")

# Callable the routes layer passes so we can swap WebSocket.send_json for tests.
SendFn = Callable[[dict[str, Any]], Awaitable[None]]


def write_stl_to_studio(run_id: str) -> bool:
    """Copy the best available STL into the ForgeCAD Studio workspace and
    write a 1-line importMesh loader so Studio live-reloads the geometry.

    Prefers solid_repaired.stl (mesh-repaired) over solid.stl if available.
    Writes artifacts/forgecad/solid.stl + artifacts/forgecad/main.forge.js.
    Returns True on success, False if the write failed (non-fatal; logged only).
    """
    from tools.artifacts import run_dir

    base = run_dir(run_id)
    repaired = base / "solid_repaired.stl"
    original = base / "solid.stl"
    stl_source = repaired if repaired.exists() else original
    try:
        _FORGECAD_WORKSPACE.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stl_source, _FORGECAD_WORKSPACE / "solid.stl")
        stub = _FORGECAD_WORKSPACE / "main.forge.js"
        stub.write_text('module.exports = importMesh("./solid.stl");\n', encoding="utf-8")
        log.info("STL copied to studio workspace: %s", stl_source)
        return True
    except OSError as exc:
        log.warning("Could not write STL to studio workspace: %s", exc)
        return False


async def run_chat_turn(
    session: DesignSession,
    user_text: str,
    send: SendFn,
    *,
    attachments: list[dict[str, Any]] | None = None,
    backend_url: str = _BACKEND_URL_DEFAULT,
) -> None:
    """Process one user message: planner turn, then optionally the geometry loop.

    Mutates *session* in place (status, history, last_plan, run_id).
    All events are emitted through *send*, which must be awaitable.
    """
    if not session.original_prompt:
        session.original_prompt = user_text
    session.history.append({"role": "user", "content": user_text})

    await send({"type": "thinking"})

    ev_loop = asyncio.get_running_loop()

    # Offload the blocking intake LLM call to a thread
    intake = await ev_loop.run_in_executor(
        None,
        lambda: run_intake_turn(
            session=session,
            user_text=user_text,
            attachments=attachments,
        )
    )
    if intake.status == "need_user":
        session.status = "needs_user"
        session.intake_state = intake.state
        session.history.append({"role": "planner", "content": intake.question})
        await send({"type": "ask_user", "question": intake.question, "options": []})
        return

    if intake.intake_context:
        session.intake_context = intake.intake_context
    session.intake_state = None

    planner_history = build_planner_history(
        original_prompt=session.original_prompt,
        chat_history=session.history,
        intake_context=session.intake_context,
    )
    run_id = new_run_id(f"design_{session.id[:8]}")
    session.run_id = run_id

    planning_event = await _emit_trace_event(
        run_id,
        send,
        source="backend",
        stage="planning",
        status="running",
        title="Planning started",
        summary="RLM planner is producing a PrimitivePlan.",
    )
    last_event_seq = int((planning_event or {}).get("seq") or 0)

    # ── 1. Planner turn (blocking RLM call → thread) ──────────────────────────
    try:
        plan = await ev_loop.run_in_executor(
            None,
            lambda: run_planner_turn(
                session.original_prompt,
                planner_history,
                backend_url=backend_url,
                run_id=run_id,
            ),
        )
    except Exception as exc:
        await _emit_trace_event(
            run_id,
            send,
            source="backend",
            stage="planning",
            status="error",
            title="Planning failed",
            summary=str(exc),
        )
        await send({"type": "error", "message": str(exc)})
        return

    # ── 2. plan → geometry loop ──────────────────────────────────────────────
    session.status = "generating"
    session.last_plan = plan_to_dict(plan)

    last_event_seq = await _emit_existing_events(run_id, send, after_seq=last_event_seq)
    plan_event = await _emit_trace_event(
        run_id,
        send,
        source="backend",
        stage="planning",
        status="ok",
        title="Plan ready",
        summary=plan.part_name,
        payload={"plan": plan_to_dict(plan)},
    )
    last_event_seq = int((plan_event or {}).get("seq") or last_event_seq)
    await send({"type": "plan", "plan": plan_to_dict(plan)})
    geometry_event = await _emit_trace_event(
        run_id,
        send,
        source="runtime",
        stage="generating",
        status="running",
        title="Geometry pipeline started",
        summary="Compiling and executing the PrimitivePlan.",
    )
    last_event_seq = int((geometry_event or {}).get("seq") or last_event_seq)
    await send({"type": "generating", "stage": "cadquery_compile"})

    # Read the toggle from the session object — set by the UI via POST /config.
    # Falls back to the TEMPORAL_HOST env var so docker-compose still works.
    use_temporal = session.use_temporal or bool(os.environ.get("TEMPORAL_HOST"))

    if use_temporal:
        await _run_via_temporal(
            session,
            plan,
            run_id,
            send,
            backend_url=backend_url,
            planner_history=planner_history,
            last_event_seq=last_event_seq,
        )
    else:
        await _run_in_process(
            session,
            plan,
            run_id,
            send,
            backend_url=backend_url,
            ev_loop=ev_loop,
            planner_history=planner_history,
            last_event_seq=last_event_seq,
        )


async def _run_in_process(
    session: DesignSession,
    plan: PrimitivePlan,
    run_id: str,
    send: SendFn,
    *,
    backend_url: str,
    ev_loop: asyncio.AbstractEventLoop,
    planner_history: list[dict[str, str]],
    last_event_seq: int,
) -> None:
    """Original path: geometry loop runs in a thread-pool executor."""
    library = load_library()
    planner_fn = _make_planner_fn(backend_url, run_id=run_id)

    try:
        result = await ev_loop.run_in_executor(
            None,
            lambda: run_geometry_loop(
                original_prompt=session.original_prompt,
                initial_plan=plan,
                planner_fn=planner_fn,
                library=library,
                run_id=run_id,
                history=planner_history,
            ),
        )
    except Exception as exc:
        session.status = "failed"
        await _emit_trace_event(
            run_id,
            send,
            source="runtime",
            stage="error",
            status="error",
            title="Geometry pipeline crashed",
            summary=str(exc),
        )
        await send({"type": "error", "message": str(exc)})
        return

    await _emit_existing_events(run_id, send, after_seq=last_event_seq)
    await _emit_loop_result(session, result, run_id, send)


async def _run_via_temporal(
    session: DesignSession,
    plan: PrimitivePlan,
    run_id: str,
    send: SendFn,
    *,
    backend_url: str,
    planner_history: list[dict[str, str]],
    last_event_seq: int,
) -> None:
    """Temporal path: start the workflow, stream its coarse-stage progress, await result.

    We do NOT block on execute_workflow. We START the workflow, then poll its
    `current_stage` query on a short timer and emit a "stage" event whenever the
    stage changes — that is what advances the chat-UI progress chips live, in lock-
    step with the Temporal UI timeline. When the workflow finishes we map its
    DesignResult to the terminal WS event.
    """
    import asyncio

    from temporal.client import get_client
    from temporal.shared import DesignInput
    from temporal.workflow import DesignWorkflow

    inp = DesignInput(
        original_prompt=session.original_prompt,
        plan_dict=plan_to_dict(plan),
        run_id=run_id,
        backend_url=backend_url,
        history=planner_history,
    )

    try:
        client = await get_client()
        handle = await client.start_workflow(
            DesignWorkflow.run,
            inp,
            id=run_id,
            task_queue=os.environ.get("TEMPORAL_TASK_QUEUE", "design"),
        )
    except Exception as exc:
        session.status = "failed"
        await send(
            {
                "type": "error",
                "message": f"Temporal error for run {run_id}: {type(exc).__name__}: {exc}",
            }
        )
        return

    # ── Stream coarse-stage progress while the workflow runs ──────────────────
    result_fut = asyncio.ensure_future(handle.result())
    last_stage: str | None = None
    while not result_fut.done():
        try:
            stage = await handle.query(DesignWorkflow.current_stage)
        except Exception:
            stage = None  # query can briefly fail at task boundaries; just re-poll
        if stage and stage != last_stage:
            last_stage = stage
            event = await _emit_trace_event(
                run_id,
                send,
                source="temporal",
                stage=stage,
                status="running",
                title=f"Temporal stage: {stage}",
            )
            last_event_seq = int((event or {}).get("seq") or last_event_seq)
            await send({"type": "stage", "stage": stage})
        # Wait up to 0.5s for completion, then loop to re-poll the stage.
        await asyncio.wait({result_fut}, timeout=0.5)
        last_event_seq = await _emit_existing_events(run_id, send, after_seq=last_event_seq)

    try:
        result_dc = await result_fut
    except Exception as exc:
        session.status = "failed"
        await _emit_trace_event(
            run_id,
            send,
            source="temporal",
            stage="error",
            status="error",
            title="Temporal workflow failed",
            summary=str(exc),
        )
        await send(
            {
                "type": "error",
                "message": f"Temporal error for run {run_id}: {type(exc).__name__}: {exc}",
            }
        )
        return

    await _emit_existing_events(run_id, send, after_seq=last_event_seq)

    # Map DesignResult dataclass → terminal WS event
    if result_dc.status == "success":
        session.status = "done"
        write_stl_to_studio(run_id)
        await _emit_trace_event(
            run_id,
            send,
            source="backend",
            stage="outcome",
            status="ok",
            title="Run succeeded",
            summary="Artifacts are ready.",
        )
        await send(
            {
                "type": "success",
                "run_id": run_id,
                "plan": result_dc.final_plan,
            }
        )
    else:
        session.status = "failed"
        await _emit_trace_event(
            run_id,
            send,
            source="backend",
            stage="outcome",
            status="error",
            title="Run failed",
            summary=result_dc.message,
            payload={"failure_category": result_dc.failure_category or "unknown"},
        )
        await send(
            {
                "type": "failed",
                "category": result_dc.failure_category or "unknown",
                "message": result_dc.message,
            }
        )


async def _emit_loop_result(
    session: DesignSession,
    result: LoopResult,
    run_id: str,
    send: SendFn,
) -> None:
    """Translate a LoopResult into WS events (in-process path)."""
    if result.status == "success":
        session.status = "done"
        write_stl_to_studio(run_id)
        await _emit_trace_event(
            run_id,
            send,
            source="backend",
            stage="outcome",
            status="ok",
            title="Run succeeded",
            summary="Artifacts are ready.",
        )
        await send(
            {
                "type": "success",
                "run_id": run_id,
                "plan": result.final_plan,
            }
        )
    else:
        session.status = "failed"
        await _emit_trace_event(
            run_id,
            send,
            source="backend",
            stage="outcome",
            status="error",
            title="Run failed",
            summary=result.message,
            payload={"failure_category": result.failure_category or "unknown"},
        )
        await send(
            {
                "type": "failed",
                "category": result.failure_category or "unknown",
                "message": result.message,
            }
        )


def _make_planner_fn(
    backend_url: str,
    *,
    run_id: str | None = None,
) -> Callable[..., PrimitivePlan]:
    """Return a PlannerFn closure for the geometry loop's replan path.

    Uses the scoped run_replanner_turn (read-only pull tools, no delegate_features
    fork tool) — mirrors temporal.activities.replan_activity so the in-process and
    Temporal paths behave the same on a replan. Failure feedback arrives in
    `history` (appended by replan_with_feedback).
    """

    def _fn(original_prompt: str, history: list[dict[str, str]]) -> PrimitivePlan:
        return run_replanner_turn(
            original_prompt,
            history,
            backend_url=backend_url,
            run_id=run_id,
        )

    return _fn


async def _emit_trace_event(
    run_id: str,
    send: SendFn,
    *,
    source: str,
    stage: str,
    status: str,
    title: str,
    summary: str = "",
    payload: dict[str, Any] | None = None,
    artifact_refs: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Persist and stream one timeline event; never crash the user run."""
    try:
        event = append_event(
            run_id,
            source=source,
            stage=stage,
            status=status,
            title=title,
            summary=summary,
            payload=payload,
            artifact_refs=artifact_refs,
        )
        await send({"type": "trace_event", "event": event})
        return event
    except Exception as exc:
        log.warning("could not emit trace event for %s: %s", run_id, exc)
        return None


async def _emit_existing_events(run_id: str, send: SendFn, *, after_seq: int) -> int:
    """Stream persisted events once after blocking RLM/runtime work completes."""
    max_seq = after_seq
    try:
        for event in list_events(run_id):
            seq = int(event.get("seq") or 0)
            if seq <= after_seq:
                continue
            await send({"type": "trace_event", "event": event})
            max_seq = max(max_seq, seq)
    except Exception as exc:
        log.warning("could not replay trace events for %s: %s", run_id, exc)
    return max_seq


def run_intake_turn(
    *,
    session: DesignSession,
    user_text: str,
    attachments: list[dict[str, Any]] | None = None,
) -> IntakeOutcome:
    """Run the pre-RLM intake step for one websocket message."""
    parsed_attachments = parse_incoming_attachments(attachments)
    return start_or_resume_intake(
        user_prompt=session.original_prompt or user_text,
        incoming_text=user_text,
        attachments=parsed_attachments,
        state=session.intake_state,
    )
