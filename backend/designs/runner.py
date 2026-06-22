"""Chat-turn orchestrator: planner → geometry loop → ForgeCAD compile.

One async function (`run_chat_turn`) drives the full pipeline for a single user
message. Blocking work (RLM call, geometry loop, ForgeCAD compile) is dispatched
to a thread-pool executor so the event loop stays free for WS I/O.

Event protocol (Server → Client, JSON):
  {"type": "thinking"}                            — planner is working
  {"type": "ask_user", "question", "options"}     — planner needs more info
  {"type": "generating", "stage"}                 — geometry loop running
  {"type": "success", "forge_js", "run_id", "plan"} — part produced
  {"type": "needs_user", "question", "options"}   — loop escalated to user
  {"type": "failed", "category", "message"}       — exhausted / permanent error
  {"type": "error", "message"}                    — unexpected exception
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from backend.designs.models import DesignSession
from runtime.compile_forge import compile_plan_to_forge
from runtime.loop import LoopResult, run_geometry_loop
from runtime.planner import PlannerOutput, run_planner_turn, run_replanner_turn
from runtime.schema import PrimitivePlan, load_library, plan_to_dict
from tools.artifacts import new_run_id

log = logging.getLogger(__name__)

# Absolute path to the ForgeCAD Studio workspace (mounted at /workspace in the
# forgecad-studio container, bound to ./artifacts/forgecad on the host).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FORGECAD_WORKSPACE = _REPO_ROOT / "artifacts" / "forgecad"

_BACKEND_URL_DEFAULT = os.environ.get("BACKEND_URL", "http://localhost:8001")
_USE_TEMPORAL = bool(os.environ.get("TEMPORAL_HOST"))

# Callable the routes layer passes so we can swap WebSocket.send_json for tests.
SendFn = Callable[[dict[str, Any]], Awaitable[None]]


def write_forge_js_to_studio(forge_js: str) -> bool:
    """Persist forge_js to the ForgeCAD Studio workspace so the live-reload picks it up.

    Writes to artifacts/forgecad/main.forge.js — the file the forgecad-studio
    container is watching via its Docker volume mount. The Studio automatically
    re-renders on file change (no iframe reload needed on the client side).

    Returns True on success, False if the write failed (non-fatal; logged only).
    """
    try:
        _FORGECAD_WORKSPACE.mkdir(parents=True, exist_ok=True)
        target = _FORGECAD_WORKSPACE / "main.forge.js"
        target.write_text(forge_js, encoding="utf-8")
        log.info("forge_js written to studio workspace: %s", target)
        return True
    except OSError as exc:
        log.warning("Could not write forge_js to studio workspace: %s", exc)
        return False


async def run_chat_turn(
    session: DesignSession,
    user_text: str,
    send: SendFn,
    *,
    backend_url: str = _BACKEND_URL_DEFAULT,
) -> None:
    """Process one user message: planner turn, then optionally the geometry loop.

    Mutates *session* in place (status, history, last_plan, forge_js, run_id).
    All events are emitted through *send*, which must be awaitable.
    """
    if not session.original_prompt:
        session.original_prompt = user_text
    session.history.append({"role": "user", "content": user_text})

    await send({"type": "thinking"})

    ev_loop = asyncio.get_running_loop()

    # ── 1. Planner turn (blocking RLM call → thread) ──────────────────────────
    try:
        output = await ev_loop.run_in_executor(
            None,
            lambda: run_planner_turn(
                session.original_prompt, session.history, backend_url=backend_url
            ),
        )
    except Exception as exc:
        await send({"type": "error", "message": str(exc)})
        return

    if output.action == "ask_user":
        session.history.append({"role": "planner", "content": output.question or ""})
        await send(
            {
                "type": "ask_user",
                "question": output.question,
                "options": output.suggested_options,
            }
        )
        return

    # ── 2. plan_ready → geometry loop ────────────────────────────────────────
    plan = output.plan
    if plan is None:
        await send({"type": "error", "message": "planner returned plan_ready with no plan"})
        return
    session.status = "generating"
    session.last_plan = plan_to_dict(plan)
    run_id = new_run_id(f"design_{session.id[:8]}")
    session.run_id = run_id

    await send({"type": "generating", "stage": "cadquery_compile"})

    if _USE_TEMPORAL:
        await _run_via_temporal(session, plan, run_id, send, backend_url=backend_url)
    else:
        await _run_in_process(session, plan, run_id, send, backend_url=backend_url, ev_loop=ev_loop)


async def _run_in_process(
    session: DesignSession,
    plan: PrimitivePlan,
    run_id: str,
    send: SendFn,
    *,
    backend_url: str,
    ev_loop: asyncio.AbstractEventLoop,
) -> None:
    """Original path: geometry loop runs in a thread-pool executor."""
    library = load_library()
    planner_fn = _make_planner_fn(backend_url)

    try:
        result = await ev_loop.run_in_executor(
            None,
            lambda: run_geometry_loop(
                original_prompt=session.original_prompt,
                initial_plan=plan,
                planner_fn=planner_fn,
                library=library,
                run_id=run_id,
            ),
        )
    except Exception as exc:
        session.status = "failed"
        await send({"type": "error", "message": str(exc)})
        return

    await _emit_loop_result(session, plan, result, run_id, send, ev_loop=ev_loop)


async def _run_via_temporal(
    session: DesignSession,
    plan: PrimitivePlan,
    run_id: str,
    send: SendFn,
    *,
    backend_url: str,
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
        session.forge_js = result_dc.forge_js or None
        session.status = "done"
        # Write to Studio workspace so ForgeCAD live-reloads the new part.
        if result_dc.forge_js:
            write_forge_js_to_studio(result_dc.forge_js)
        await send(
            {
                "type": "success",
                "forge_js": result_dc.forge_js or None,
                "run_id": run_id,
                "plan": result_dc.final_plan,
            }
        )
    elif result_dc.status == "needs_user":
        question = result_dc.question or "Can you clarify the design requirements?"
        session.status = "needs_user"
        session.history.append({"role": "planner", "content": question})
        await send({"type": "needs_user", "question": question, "options": []})
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
    plan: PrimitivePlan,
    result: LoopResult,
    run_id: str,
    send: SendFn,
    *,
    ev_loop: asyncio.AbstractEventLoop,
) -> None:
    """Translate a LoopResult into WS events (in-process path)."""
    library = load_library()
    if result.status == "success":
        try:
            forge_js: str | None = await ev_loop.run_in_executor(
                None, lambda: compile_plan_to_forge(plan, library)
            )
        except Exception:
            forge_js = None
        session.forge_js = forge_js
        session.status = "done"
        # Write to Studio workspace so ForgeCAD live-reloads the new part.
        if forge_js:
            write_forge_js_to_studio(forge_js)
        await send(
            {
                "type": "success",
                "forge_js": forge_js,
                "run_id": run_id,
                "plan": result.final_plan,
            }
        )
    elif result.status == "needs_user":
        question = result.question or "Can you clarify the design requirements?"
        session.status = "needs_user"
        session.history.append({"role": "planner", "content": question})
        await send({"type": "needs_user", "question": question, "options": []})
    else:
        session.status = "failed"
        await send(
            {
                "type": "failed",
                "category": result.failure_category or "unknown",
                "message": result.message,
            }
        )


def _make_planner_fn(backend_url: str) -> Callable[..., PlannerOutput]:
    """Return a PlannerFn closure for the geometry loop's replan path.

    Uses run_replanner_turn (no tools, single REPL step) so replans never
    hit the tool-cascade timeout that affects run_planner_turn.
    """

    def _fn(original_prompt: str, history: list[dict[str, str]]) -> PlannerOutput:
        return run_replanner_turn(original_prompt, history)

    return _fn
