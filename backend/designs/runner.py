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
  {"type": "approved", "run_id", "status"}        — design saved to the flywheel reference store
  {"type": "ask_user", "question", "options"}     — pre-planner intake OR edit clarification

The planner/replanner never ask the user a clarifying question — they always
resolve ambiguity themselves and return a plan, or the turn fails outright.
The ONLY user-facing questions come from the intake chatbot, either before the
first plan (fresh design) or before an edit replan (post-design edit request).

Once a design reaches "done"/"failed", the session does NOT reset — the next
message is classified as a QUESTION about the current model (answered directly),
an EDIT request (clarified via the same intake engine, then applied via
replan_for_edit on a fresh run_id), or an APPROVAL (a pure positive sign-off →
the design is persisted to the flywheel reference store for future planning).
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
from backend.approved_store.store import append_approved
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
            f'// run: {run_id}\nmodule.exports = importMesh("./solid.stl");\n',
            encoding="utf-8",
        )
        log.info("STL copied to studio workspace: %s", stl_source)
        return True
    except OSError as exc:
        log.warning("Could not write STL to studio workspace: %s", exc)
        return False


async def cancel_run(session: DesignSession) -> dict[str, Any]:
    """Best-effort cancel of an in-flight run.

    Temporal path: cancels the workflow (its id == run_id) cleanly — this makes
    the streaming ``handle.result()`` await in ``_run_via_temporal`` raise, so the
    WS turn emits a terminal event on its own.

    In-process path: only a cooperative flag is set — the geometry loop runs in a
    thread-pool executor with no cancel token, so a stage already in flight (e.g.
    a CadQuery subprocess) runs to completion in the background. The session is
    still marked cancelled so the UI and any post-run logic can react.
    """
    session.cancelled = True
    session.status = "cancelled"

    workflow_cancelled = False
    if _USE_TEMPORAL and session.run_id:
        from temporal.client import get_client

        client = await get_client()
        handle = client.get_workflow_handle(session.run_id)
        await handle.cancel()
        workflow_cancelled = True

    return {
        "status": "cancelled",
        "run_id": session.run_id,
        "workflow_cancelled": workflow_cancelled,
    }


def _persist_approval(session: DesignSession) -> dict[str, Any]:
    """Write the current successful design to the flywheel store (sync; run in an
    executor). Stores last_plan + run_id as a pair so the plan matches its
    outputs/{run_id}/ artifacts. Idempotent by run_id inside append_approved.

    Guards on status=="done" itself (belt-and-braces: the chat approval branch
    runs inside _run_post_design_turn, which also fires after a FAILED run — must
    never store a stale/failed plan). Returns {"status": "not_approvable"} if so.
    """
    if session.status != "done" or not session.run_id or not session.last_plan:
        return {"status": "not_approvable", "run_id": session.run_id}
    return append_approved(
        run_id=session.run_id,
        original_prompt=session.original_prompt,
        plan=session.last_plan,
        intake_context=session.intake_context,
        feature_checklist=session.feature_checklist,
    )


async def approve_run(session: DesignSession) -> dict[str, Any]:
    """Persist the current successful design as a reusable reference (flywheel).

    Backs POST /designs/{id}/approve. The route gates on a finished run (like
    handoff); the append itself is idempotent by run_id, so re-approving returns
    'already_approved'. File I/O runs in the default executor.
    """
    ev_loop = asyncio.get_running_loop()
    return await ev_loop.run_in_executor(None, lambda: _persist_approval(session))


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
    if intake.feature_checklist:
        session.feature_checklist = intake.feature_checklist
    session.intake_state = None

    planner_history = build_planner_history(
        original_prompt=session.original_prompt,
        chat_history=session.history,
        intake_context=session.intake_context,
    )

    # ── Geometry pipeline ─────────────────────────────────────────────────────
    session.status = "generating"
    run_id = new_run_id(f"design_{session.id[:8]}")
    session.run_id = run_id

    # Base replan history: the pre-planner intake facts ONLY — never the raw
    # chatbot conversation. Replans build plan-lineage state on top of this.
    replan_base_history: list[dict[str, str]] = (
        [
            {
                "role": "user",
                "content": f"Established design facts from intake:\n{session.intake_context}",
            }
        ]
        if session.intake_context
        else []
    )

    if _USE_TEMPORAL:
        # Temporal PLANS as its first activity — start the workflow immediately so
        # there is NO in-process planner blocking before Temporal (that was the long
        # dead gap after the last answer). Pass no plan + the planner history; the
        # workflow's plan_activity produces the plan.
        await send({"type": "generating", "stage": "planning", "run_id": run_id})
        await _run_via_temporal(
            session, None, run_id, send,
            backend_url=backend_url, history=replan_base_history,
            planner_history=planner_history,
        )
    else:
        # In-process fallback: run the planner locally, then the geometry loop.
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
        session.last_plan = plan_to_dict(plan)
        await send({"type": "generating", "stage": "cadquery_compile", "run_id": run_id})
        await _run_in_process(
            session,
            plan,
            run_id,
            send,
            backend_url=backend_url,
            ev_loop=ev_loop,
            history=replan_base_history,
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
                feature_checklist=session.feature_checklist,
            ),
        )
    except Exception as exc:
        session.status = "failed"
        await send({"type": "error", "message": str(exc)})
        return

    await _emit_loop_result(session, result, run_id, send)


async def _run_via_temporal(
    session: DesignSession,
    plan: PrimitivePlan | None,
    run_id: str,
    send: SendFn,
    *,
    backend_url: str,
    history: list[dict[str, str]] | None = None,
    verify_prompt: str | None = None,
    planner_history: list[dict[str, str]] | None = None,
    edit_text: str = "",
    last_plan: PrimitivePlan | None = None,
) -> None:
    """Temporal path: start the workflow, stream its coarse-stage progress, await result.

    We do NOT block on execute_workflow. We START the workflow, then poll its
    `current_stage` query on a short timer and emit a "stage" event whenever the
    stage changes — that is what advances the chat-UI progress chips live, in lock-
    step with the Temporal UI timeline. When the workflow finishes we map its
    DesignResult to the terminal WS event.

    plan: a ready PrimitivePlan → the workflow skips planning entirely. None +
    edit_text set → the workflow's FIRST activity is edit_activity (applies
    edit_text to last_plan on the worker) instead of plan_activity. None + no
    edit_text (fresh design) → plan_dict is empty and plan_activity produces the
    plan as the first stage, so the workflow starts the instant intake completes.
    verify_prompt: see _run_in_process — same edit-aware grounding, threaded
    into DesignInput.original_prompt so the activity-side verifier sees it.
    """
    import asyncio

    from temporal.client import get_client
    from temporal.shared import DesignInput
    from temporal.workflow import DesignWorkflow

    task_queue = os.environ.get("TEMPORAL_TASK_QUEUE", "design")
    inp = DesignInput(
        original_prompt=verify_prompt or session.original_prompt,
        run_id=run_id,
        plan_dict=plan_to_dict(plan) if plan is not None else {},
        backend_url=backend_url,
        history=list(history or []),
        feature_checklist=session.feature_checklist,
        planner_history=list(planner_history or []),
        edit_text=edit_text,
        last_plan_dict=plan_to_dict(last_plan) if last_plan is not None else {},
    )

    try:
        client = await get_client()
        log.info("Starting DesignWorkflow %s on task queue %r", run_id, task_queue)
        handle = await client.start_workflow(
            DesignWorkflow.run,
            inp,
            id=run_id,
            task_queue=task_queue,
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
        # The workflow may have PRODUCED the plan (plan_activity), so persist the
        # final plan onto the session — post-design edits/questions depend on it.
        if result_dc.final_plan:
            session.last_plan = result_dc.final_plan
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
        if result_dc.final_plan:
            session.last_plan = result_dc.final_plan
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

    if kind == "approval":
        # A pure positive sign-off → persist the design as a reusable reference.
        # Re-check the gate here (this turn also runs after a FAILED run) so a
        # stale/failed plan never enters the flywheel.
        if session.status != "done" or not session.run_id or not session.last_plan:
            msg = "Nothing to approve yet — the last design didn't finish successfully."
            session.history.append({"role": "planner", "content": msg})
            await send({"type": "answer", "text": msg})
            return
        result = await ev_loop.run_in_executor(None, lambda: _persist_approval(session))
        session.history.append(
            {"role": "planner", "content": "Approved — saved as a reference pattern for future designs."}
        )
        await send({"type": "approved", "run_id": session.run_id, "status": result.get("status", "approved")})
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
    write_stl_to_studio always points ForgeCAD Studio at the newest one).

    Under Temporal, the replan-for-edit step itself runs INSIDE the workflow
    (edit_activity, the workflow's first activity when edit_text is set) so the
    whole edit is one durable execution on the worker — not a bare in-process
    call from this backend process that has no retry and dies with the
    container. The in-process fallback below is unchanged.
    """
    last_plan = PrimitivePlan.model_validate(session.last_plan)
    prior_history: list[dict[str, str]] = (
        [
            {
                "role": "user",
                "content": f"Established design facts from intake:\n{session.intake_context}",
            }
        ]
        if session.intake_context
        else []
    )

    run_id = new_run_id(f"design_{session.id[:8]}")
    session.run_id = run_id

    # Fold this edit into intake_context (the same "established facts" field
    # the fresh-design flow uses) so every FUTURE replan/edit in this session
    # keeps seeing it — not just this one run. Independent of the plan itself,
    # so this happens up front for both the Temporal and in-process paths.
    session.intake_context = (
        f"{session.intake_context}\n- edit applied: {edit_text}".strip()
        if session.intake_context
        else f"- edit applied: {edit_text}"
    )

    replan_base_history: list[dict[str, str]] = [
        {
            "role": "user",
            "content": f"Established design facts from intake:\n{session.intake_context}",
        }
    ]

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
        session.status = "generating"
        await send({"type": "generating", "stage": "editing", "run_id": run_id})
        await _run_via_temporal(
            session,
            None,
            run_id,
            send,
            backend_url=backend_url,
            history=replan_base_history,
            verify_prompt=verify_prompt,
            edit_text=edit_text,
            last_plan=last_plan,
        )
        return

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
    await send({"type": "generating", "stage": "cadquery_compile", "run_id": run_id})
    await _run_in_process(
        session,
        plan,
        run_id,
        send,
        backend_url=backend_url,
        ev_loop=ev_loop,
        history=replan_base_history,
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


def run_design_sync(prompt: str, run_id: str, backend_url: str):
    """Synchronous prompt -> LoopResult: plan + full geometry loop, no session/WS.

    The clean entry the eval harness (eval/benchmark.py --mode full) uses to
    exercise the REAL agent loop (planner writes the code, replanner repairs it)
    instead of executing a reference snippet. wall_start is taken BEFORE planning
    so the trace's duration_s reflects the FULL single-part workflow time (the
    PRD "<5 min" gate), not just the geometry loop. Requires a running backend at
    backend_url (the planner pull-tools hit its /internal endpoints)."""
    import os
    import time

    from runtime.loop import run_geometry_loop
    from runtime.planner import run_planner_turn
    from runtime.schema import load_library

    os.environ["DTCM_BACKEND_URL"] = backend_url
    t0 = time.monotonic()
    plan = run_planner_turn(prompt, [], backend_url=backend_url)
    return run_geometry_loop(
        original_prompt=prompt,
        initial_plan=plan,
        planner_fn=_make_planner_fn(backend_url),
        library=load_library(),
        run_id=run_id,
        wall_start=t0,
    )


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
