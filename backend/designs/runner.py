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
  {"type": "answer", "text"}                      — post-design Q&A reply, no geometry change
  {"type": "ask_user", "question", "options"}     — pre-planner intake OR edit clarification

The planner/replanner never ask the user a clarifying question — they always
resolve ambiguity themselves and return a plan, or the turn fails outright.
The ONLY user-facing questions come from the intake chatbot, either before the
first plan (fresh design) or before an edit replan (post-design edit request).

Once a design reaches "done"/"failed", the session does NOT reset — the next
message is classified as either a QUESTION about the current model (answered
directly, no regeneration) or an EDIT request (clarified via the same intake
engine, then applied via replan_for_edit on a fresh run_id).
"""

from __future__ import annotations

import asyncio
import json
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
    start_or_resume_edit_intake,
    start_or_resume_intake,
)
from backend.designs.models import DesignSession
from runtime.loop import LoopResult, run_geometry_loop
from runtime.planner import run_planner_turn, run_replanner_turn
from runtime.replan import replan_for_edit
from runtime.schema import PrimitivePlan, load_library, plan_to_dict
from tools.artifacts import new_run_id
from tools.load_trace import load_trace
from tools.vlm_intake import answer_model_question, classify_post_design_message

log = logging.getLogger(__name__)

# Absolute path to the ForgeCAD Studio workspace (mounted at /workspace in the
# forgecad-studio container, bound to ./artifacts/forgecad on the host).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FORGECAD_WORKSPACE = _REPO_ROOT / "artifacts" / "forgecad"

_BACKEND_URL_DEFAULT = os.environ.get("BACKEND_URL", "http://localhost:8001")
_USE_TEMPORAL = bool(os.environ.get("TEMPORAL_HOST"))

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
        stub.write_text(
            f"// run: {run_id}\n"
            'module.exports = importMesh("./solid.stl");\n',
            encoding="utf-8",
        )
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

    Routing, in order:
    1. Mid-edit-clarification (`pending_edit_text` set) → resume that, regardless
       of `status` (a clarification round leaves status at "needs_user", same as
       the pre-planner intake — `pending_edit_text` is what disambiguates which
       flow a "needs_user" reply belongs to).
    2. A prior design already finished (`status` done/failed + a `last_plan`
       exists) → post-design turn: classify question vs. edit.
    3. Otherwise → the original from-scratch flow (pre-planner intake → planner).
    """
    if not session.original_prompt:
        session.original_prompt = user_text
    session.history.append({"role": "user", "content": user_text})

    await send({"type": "thinking"})

    ev_loop = asyncio.get_running_loop()

    if session.pending_edit_text:
        await _resume_edit_clarification(
            session, user_text, send, backend_url=backend_url, ev_loop=ev_loop
        )
        return

    if session.status in ("done", "failed") and session.last_plan:
        await _run_post_design_turn(
            session, user_text, send, backend_url=backend_url, ev_loop=ev_loop
        )
        return

    intake = await ev_loop.run_in_executor(
        None,
        lambda: run_intake_turn(
            session=session,
            user_text=user_text,
            attachments=attachments,
        ),
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

    # ── 1. Planner turn (blocking RLM call → thread) ──────────────────────────
    try:
        plan = await ev_loop.run_in_executor(
            None,
            lambda: run_planner_turn(
                session.original_prompt, planner_history, backend_url=backend_url
            ),
        )
    except Exception as exc:
        await send({"type": "error", "message": str(exc)})
        return

    # ── 2. plan → geometry loop ──────────────────────────────────────────────
    session.status = "generating"
    session.last_plan = plan_to_dict(plan)
    run_id = new_run_id(f"design_{session.id[:8]}")
    session.run_id = run_id

    await send({"type": "generating", "stage": "cadquery_compile"})

    # Base replan history: the pre-planner intake facts ONLY — never the raw
    # chatbot conversation. Replans build plan-lineage state on top of this.
    replan_base_history: list[dict[str, str]] = (
        [{"role": "user", "content": f"Established design facts from intake:\n{session.intake_context}"}]
        if session.intake_context
        else []
    )

    if _USE_TEMPORAL:
        await _run_via_temporal(
            session, plan, run_id, send,
            backend_url=backend_url, history=replan_base_history,
        )
    else:
        await _run_in_process(
            session, plan, run_id, send,
            backend_url=backend_url, ev_loop=ev_loop, history=replan_base_history,
        )


async def _run_in_process(
    session: DesignSession,
    plan: PrimitivePlan,
    run_id: str,
    send: SendFn,
    *,
    backend_url: str,
    ev_loop: asyncio.AbstractEventLoop,
    history: list[dict[str, str]] | None = None,
    verify_prompt: str | None = None,
) -> None:
    """Original path: geometry loop runs in a thread-pool executor.

    verify_prompt grounds the VLM verifier (and any in-loop replan-on-failure
    call) — defaults to the original design prompt, but an edit turn passes
    the original + the edit request so the verifier judges the model against
    what the user actually wants NOW, not the stale pre-edit intent.
    """
    library = load_library()
    planner_fn = _make_planner_fn(backend_url)

    try:
        result = await ev_loop.run_in_executor(
            None,
            lambda: run_geometry_loop(
                original_prompt=verify_prompt or session.original_prompt,
                initial_plan=plan,
                planner_fn=planner_fn,
                library=library,
                run_id=run_id,
                history=history,
            ),
        )
    except Exception as exc:
        session.status = "failed"
        await send({"type": "error", "message": str(exc)})
        return

    await _emit_loop_result(session, result, run_id, send)


async def _run_via_temporal(
    session: DesignSession,
    plan: PrimitivePlan,
    run_id: str,
    send: SendFn,
    *,
    backend_url: str,
    history: list[dict[str, str]] | None = None,
    verify_prompt: str | None = None,
) -> None:
    """Temporal path: start the workflow, stream its coarse-stage progress, await result.

    We do NOT block on execute_workflow. We START the workflow, then poll its
    `current_stage` query on a short timer and emit a "stage" event whenever the
    stage changes — that is what advances the chat-UI progress chips live, in lock-
    step with the Temporal UI timeline. When the workflow finishes we map its
    DesignResult to the terminal WS event.

    verify_prompt: see _run_in_process — same edit-aware grounding, threaded
    into DesignInput.original_prompt so the activity-side verifier sees it.
    """
    import asyncio

    from temporal.client import get_client
    from temporal.shared import DesignInput
    from temporal.workflow import DesignWorkflow

    inp = DesignInput(
        original_prompt=verify_prompt or session.original_prompt,
        plan_dict=plan_to_dict(plan),
        run_id=run_id,
        backend_url=backend_url,
        history=list(history or []),
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
        await send({"type": "error", "message": f"Temporal error: {exc}"})
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
            await send({"type": "stage", "stage": stage})
        # Wait up to 0.5s for completion, then loop to re-poll the stage.
        await asyncio.wait({result_fut}, timeout=0.5)

    try:
        result_dc = await result_fut
    except Exception as exc:
        session.status = "failed"
        await send({"type": "error", "message": f"Temporal error: {exc}"})
        return

    # Map DesignResult dataclass → terminal WS event
    if result_dc.status == "success":
        session.status = "done"
        write_stl_to_studio(run_id)
        await send(
            {
                "type": "success",
                "run_id": run_id,
                "plan": result_dc.final_plan,
            }
        )
    else:
        session.status = "failed"
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
        await send(
            {
                "type": "success",
                "run_id": run_id,
                "plan": result.final_plan,
            }
        )
    else:
        session.status = "failed"
        await send(
            {
                "type": "failed",
                "category": result.failure_category or "unknown",
                "message": result.message,
            }
        )


async def _run_post_design_turn(
    session: DesignSession,
    user_text: str,
    send: SendFn,
    *,
    backend_url: str,
    ev_loop: asyncio.AbstractEventLoop,
) -> None:
    """Route a message sent AFTER a design finished: question, or start an edit.

    Classification is a single cheap flash call (classify_post_design_message).
    A question is answered directly from the plan + trace metrics — no geometry
    regeneration. An edit hands off to the same intake-clarification engine the
    pre-planner flow uses, seeded for editing instead of a fresh design.
    """
    plan_summary = json.dumps(session.last_plan, separators=(",", ":"))
    kind = await ev_loop.run_in_executor(
        None, lambda: classify_post_design_message(user_text, plan_summary)
    )

    if kind == "question":
        try:
            answer = await ev_loop.run_in_executor(
                None,
                lambda: answer_model_question(
                    user_text,
                    session.last_plan,
                    metrics=_metrics_for_run(session.run_id),
                    render_png=_render_png_for_run(session.run_id),
                ),
            )
        except Exception as exc:
            await send({"type": "error", "message": str(exc)})
            return
        session.history.append({"role": "planner", "content": answer})
        await send({"type": "answer", "text": answer})
        return

    session.pending_edit_text = user_text
    await _resume_edit_clarification(
        session, user_text, send, backend_url=backend_url, ev_loop=ev_loop
    )


async def _resume_edit_clarification(
    session: DesignSession,
    incoming_text: str,
    send: SendFn,
    *,
    backend_url: str,
    ev_loop: asyncio.AbstractEventLoop,
) -> None:
    """One turn of edit clarification: ask on, or apply the edit once clear.

    `session.intake_state` is reused for this Q&A round-trip (it's always None
    between turns, so there's no conflict with the pre-planner intake's use of
    the same field). `session.pending_edit_text` holds the ORIGINAL edit request
    across the whole clarification round; `incoming_text` is whatever the user
    just replied with (the edit request itself on the first turn, an answer to
    the pending question on every turn after).
    """
    plan_summary = json.dumps(session.last_plan, separators=(",", ":"))
    outcome = await ev_loop.run_in_executor(
        None,
        lambda: start_or_resume_edit_intake(
            edit_text=session.pending_edit_text,
            incoming_text=incoming_text,
            plan_summary=plan_summary,
            state=session.intake_state,
        ),
    )

    if outcome.status == "need_user":
        session.status = "needs_user"
        session.intake_state = outcome.state
        session.history.append({"role": "planner", "content": outcome.question})
        await send({"type": "ask_user", "question": outcome.question, "options": []})
        return

    session.intake_state = None
    edit_text = outcome.intake_context or session.pending_edit_text
    session.pending_edit_text = ""
    await _apply_edit(session, edit_text, send, backend_url=backend_url, ev_loop=ev_loop)


async def _apply_edit(
    session: DesignSession,
    edit_text: str,
    send: SendFn,
    *,
    backend_url: str,
    ev_loop: asyncio.AbstractEventLoop,
) -> None:
    """Replan the existing model for a clarified edit, then regenerate on a
    fresh run_id (versioned: each edit keeps its own outputs/ dir on disk;
    write_stl_to_studio always points ForgeCAD Studio at the newest one)."""
    last_plan = PrimitivePlan.model_validate(session.last_plan)
    prior_history: list[dict[str, str]] = (
        [{"role": "user", "content": f"Established design facts from intake:\n{session.intake_context}"}]
        if session.intake_context
        else []
    )

    try:
        plan = await ev_loop.run_in_executor(
            None,
            lambda: replan_for_edit(
                original_prompt=session.original_prompt,
                last_plan=last_plan,
                edit_text=edit_text,
                prior_history=prior_history,
                planner_fn=_make_planner_fn(backend_url),
            ),
        )
    except Exception as exc:
        session.status = "failed"
        await send({"type": "error", "message": str(exc)})
        return

    session.status = "generating"
    session.last_plan = plan_to_dict(plan)
    run_id = new_run_id(f"design_{session.id[:8]}")
    session.run_id = run_id
    await send({"type": "generating", "stage": "cadquery_compile"})

    # Fold this edit into intake_context (the same "established facts" field
    # the fresh-design flow uses) so every FUTURE replan/edit in this session
    # keeps seeing it — not just this one run.
    session.intake_context = (
        f"{session.intake_context}\n- edit applied: {edit_text}".strip()
        if session.intake_context
        else f"- edit applied: {edit_text}"
    )

    replan_base_history: list[dict[str, str]] = (
        [{"role": "user", "content": f"Established design facts from intake:\n{session.intake_context}"}]
    )

    # The VLM verifier only ever sees this single string (no history) — it must
    # spell out the edit directly, or the verifier judges the model against the
    # stale pre-edit prompt and flags a correctly-applied edit as a defect.
    verify_prompt = (
        f"{session.original_prompt}\n\n"
        f"The model has since been edited. Established facts so far:\n{session.intake_context}\n\n"
        f"Judge the model against its CURRENT state, including all edits above — "
        f"not the original request alone."
    )

    if _USE_TEMPORAL:
        await _run_via_temporal(
            session, plan, run_id, send,
            backend_url=backend_url, history=replan_base_history, verify_prompt=verify_prompt,
        )
    else:
        await _run_in_process(
            session, plan, run_id, send,
            backend_url=backend_url, ev_loop=ev_loop, history=replan_base_history,
            verify_prompt=verify_prompt,
        )


def _render_png_for_run(run_id: str | None) -> str | None:
    """Best-effort render PNG path from the run's trace, for Q&A grounding."""
    if not run_id:
        return None
    result = load_trace(run_id)
    if not result.get("success"):
        return None
    return (result["trace"].get("renders") or {}).get("png_path") or None


def _metrics_for_run(run_id: str | None) -> dict[str, Any]:
    """Best-effort geometry metrics from the run's trace, for Q&A grounding."""
    if not run_id:
        return {}
    result = load_trace(run_id)
    if not result.get("success"):
        return {}
    trace = result["trace"]
    return {
        "execution_result": trace.get("execution_result") or {},
        "mesh_report": trace.get("mesh_report") or {},
    }


def _make_planner_fn(backend_url: str) -> Callable[..., PrimitivePlan]:
    """Return a PlannerFn closure for the geometry loop's replan path.

    Uses the scoped run_replanner_turn (read-only pull tools, no fork tool) —
    mirrors temporal.activities.replan_activity so the in-process and
    Temporal paths behave the same on a replan. `history` = the pre-planner intake
    facts base, plus each prior round's (failed plan + failure) pair accumulated
    by the geometry loop, plus the current round's feedback message appended by
    replan_with_feedback — never the raw chatbot conversation.
    """

    def _fn(original_prompt: str, history: list[dict[str, str]]) -> PrimitivePlan:
        return run_replanner_turn(original_prompt, history, backend_url=backend_url)

    return _fn


def run_intake_turn(
    *,
    session: DesignSession,
    user_text: str,
    attachments: list[dict[str, Any]] | None = None,
) -> IntakeOutcome:
    """Run the pre-RLM intake step for one websocket message."""
    return start_or_resume_intake(
        user_prompt=session.original_prompt or user_text,
        incoming_text=user_text,
        attachments=parse_incoming_attachments(attachments),
        state=session.intake_state,
    )
