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
import os
from collections.abc import Awaitable, Callable
from typing import Any

from backend.designs.models import DesignSession
from runtime.compile_forge import compile_plan_to_forge
from runtime.loop import run_geometry_loop
from runtime.planner import PlannerOutput, run_planner_turn
from runtime.schema import load_library, plan_to_dict
from tools.artifacts import new_run_id

_BACKEND_URL_DEFAULT = os.environ.get("BACKEND_URL", "http://localhost:8001")

# Callable the routes layer passes so we can swap WebSocket.send_json for tests.
SendFn = Callable[[dict[str, Any]], Awaitable[None]]


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

    # ── 2. plan_ready → geometry loop (blocking → thread) ────────────────────
    plan = output.plan
    if plan is None:
        await send({"type": "error", "message": "planner returned plan_ready with no plan"})
        return
    session.status = "generating"
    session.last_plan = plan_to_dict(plan)
    run_id = new_run_id(f"design_{session.id[:8]}")
    session.run_id = run_id

    await send({"type": "generating", "stage": "cadquery_compile"})

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

    # ── 3. Emit outcome event ─────────────────────────────────────────────────
    if result.status == "success":
        try:
            forge_js: str | None = await ev_loop.run_in_executor(
                None, lambda: compile_plan_to_forge(plan, library)
            )
        except Exception:
            forge_js = None
        session.forge_js = forge_js
        session.status = "done"
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
    """Return a PlannerFn closure for the geometry loop's replan path."""

    def _fn(original_prompt: str, history: list[dict[str, str]]) -> PlannerOutput:
        return run_planner_turn(original_prompt, history, backend_url=backend_url)

    return _fn
