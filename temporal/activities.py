"""Temporal activities — one coarse activity per pipeline stage (diagram 03.1).

Each activity is a thin @activity.defn wrapper around the pure, Temporal-free
helpers in runtime/. Activities are the only place Temporal touches real compute;
they run synchronously and Temporal's Worker dispatches them on a thread-pool
executor (see temporal/worker.py).

The DesignWorkflow orchestrates these and owns the bounded repair loop, so each
activity does exactly ONE coarse stage and returns a typed result:

  generate_activity  — compile CadQuery + .forge.js (parallel), execute, inspect,
                       repair, render  -> GenerateOutput
  verify_activity    — multimodal verify against intent                -> VerifyOutput
  replan_activity    — scoped replanner fixes the plan from a failure  -> ReplanOutput
  record_trace_activity — write the auditable trace.json (artifact store)

Timeouts and retry policy live on the workflow side, not here.
"""

from __future__ import annotations

import contextvars
import logging
import threading
from contextlib import contextmanager

from temporalio import activity

logger = logging.getLogger(__name__)


_HEARTBEAT_INTERVAL_S = 10.0


@contextmanager
def _heartbeating(interval_s: float = _HEARTBEAT_INTERVAL_S):
    """Emit activity.heartbeat() every `interval_s` while the activity body runs.

    These are SYNC activities on a thread-pool executor — the activity thread is
    fully blocked in real compute (OCCT, VTK, a Gemini call, the fast-rlm
    subprocess), so heartbeats must come from a side thread. The activity context
    lives in a contextvar, so the side thread runs under a copy of the current
    context to reach it. Paired with heartbeat_timeout on the workflow side, this
    lets Temporal detect a hung/dead worker in ~1 minute instead of only at the
    activity's schedule_to_close ceiling (up to 1h for replan).
    """
    stop = threading.Event()
    ctx = contextvars.copy_context()

    def _beat() -> None:
        while not stop.wait(interval_s):
            try:
                activity.heartbeat()
            except Exception:  # noqa: BLE001 — context gone = activity finished/cancelled
                return

    thread = threading.Thread(target=lambda: ctx.run(_beat), daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1.0)

# Pure single-attempt helpers shared with the in-process loop (runtime is the
# canonical, Temporal-free home of stage logic; temporal/ depends on runtime/).
from runtime.loop import _Artifacts, _run_geometry, _run_verify
from runtime.planner import run_replanner_turn
from runtime.replan import replan_with_feedback
from runtime.schema import PrimitivePlan, load_library, plan_to_dict
from runtime.trace import build_trace, category_for_stage, write_trace
from temporal.shared import (
    CompileInput,
    CompileOutput,
    ExecuteInput,
    ExecuteOutput,
    GenerateInput,
    GenerateOutput,
    InspectInput,
    InspectOutput,
    RenderInput,
    RenderOutput,
    RepairInput,
    RepairOutput,
    ReplanInput,
    ReplanOutput,
    TraceInput,
    VerifyInput,
    VerifyOutput,
)


@activity.defn
def generate_activity(inp: GenerateInput) -> GenerateOutput:
    """GENERATING: compile CadQuery, execute, inspect, repair, render.

    Reuses runtime.loop._run_geometry. A failure in any sub-step (compile, execute,
    mesh repair) comes back as a tagged GenerateOutput the workflow routes to the replanner.
    """
    library = load_library()
    plan = PrimitivePlan.model_validate(inp.plan_dict)
    art = _Artifacts()

    failure = _run_geometry(plan, library, inp.run_id, art)

    return GenerateOutput(
        ok=failure is None,
        failure_stage="" if failure is None else failure.stage,
        failure_detail="" if failure is None else failure.detail,
        code=art.code or "",
        execution_result=art.execution_result or {},
        mesh_report=art.mesh_report or {},
        renders=art.renders or {},
    )


# ── Per-step generate activities (split of generate_activity) ────────────────────
# Each wraps ONE pure tool so the Temporal timeline shows compile → execute →
# inspect → repair → render as distinct events. STL handoff is by file path on the
# shared ./outputs volume. The workflow owns the branching (repair only on inspect
# fail) and maps each failure_stage to the replan loop.


@activity.defn
def compile_activity(inp: CompileInput) -> CompileOutput:
    """GENERATING(compile): plan -> CadQuery source."""
    from runtime.compile_cadquery import CompileError, compile_plan_to_cadquery

    library = load_library()
    plan = PrimitivePlan.model_validate(inp.plan_dict)
    try:
        code = compile_plan_to_cadquery(plan, library)
    except CompileError as exc:
        stage = "primitive_gap" if "primitive_gap" in str(exc) else "cadquery_compile"
        return CompileOutput(ok=False, failure_stage=stage, failure_detail=str(exc))
    return CompileOutput(ok=True, code=code)


@activity.defn
def execute_activity(inp: ExecuteInput) -> ExecuteOutput:
    """GENERATING(execute): run the CadQuery script -> solid + STL/STEP on disk."""
    from tools.execute_cadquery import execute_cadquery

    with _heartbeating():
        res = execute_cadquery(inp.code, inp.run_id)
    if not res.get("success"):
        return ExecuteOutput(
            ok=False, execution_result=res,
            failure_stage="cadquery_execute", failure_detail=str(res.get("error")),
        )
    return ExecuteOutput(ok=True, execution_result=res, stl_path=res["stl_path"])


@activity.defn
def inspect_activity(inp: InspectInput) -> InspectOutput:
    """INSPECTING: MeshLib watertight / manifold check (drives the repair branch)."""
    from tools.inspect_mesh import inspect_mesh

    report = inspect_mesh(inp.stl_path)
    return InspectOutput(passes=bool(report.get("passes")), mesh_report=report)


@activity.defn
def repair_activity(inp: RepairInput) -> RepairOutput:
    """REPAIRING: MeshLib repair (runs only when inspect failed)."""
    from runtime.replan import collect_feedback_detail
    from tools.repair_mesh import repair_mesh

    with _heartbeating():
        repair = repair_mesh(inp.stl_path, inp.run_id)
    after = repair.get("after", {})
    if not repair.get("passes"):
        return RepairOutput(
            passes=False, mesh_report=after,
            failure_stage="mesh_repair",
            failure_detail=collect_feedback_detail("mesh_repair", repair),
        )
    return RepairOutput(passes=True, mesh_report=after, repaired_stl_path=repair["repaired_stl_path"])


@activity.defn
def render_activity(inp: RenderInput) -> RenderOutput:
    """GENERATING(render): three-view PNG render of the final STL for the verifier."""
    from tools.render_views import render_views

    with _heartbeating():
        renders = render_views(inp.stl_path, inp.run_id, section=inp.section)
    if not renders.get("success"):
        return RenderOutput(
            ok=False, renders=renders,
            failure_stage="cadquery_execute", failure_detail=str(renders.get("error")),
        )
    return RenderOutput(ok=True, renders=renders)


@activity.defn
def verify_activity(inp: VerifyInput) -> VerifyOutput:
    """VERIFYING: run the multimodal verifier against the rendered geometry + metrics.

    Rebuilds the minimal _Artifacts the verifier reads, then reuses
    runtime.loop._run_verify so the verdict + visual_mismatch feedback logic is
    identical to the in-process path.
    """
    art = _Artifacts(
        execution_result=inp.execution_result,
        mesh_report=inp.mesh_report,
        renders=inp.renders,
        feedback_log=list(inp.prior_feedback),
    )

    # Empty code string: verify_geometry keeps `code` in its signature for the
    # in-process loop's call shape but never sends it to the judge — the VLM
    # reads prompt + render PNG + last feedback only.
    with _heartbeating():
        failure = _run_verify(inp.prompt, "", art)

    return VerifyOutput(
        passed=failure is None,
        feedback="" if failure is None else failure.detail,
        verdict=art.verdict or {},
    )


@activity.defn
def replan_activity(inp: ReplanInput) -> ReplanOutput:
    """REPLANNING: fix the plan from the failure message via the scoped replanner.

    Reuses runtime.replan.replan_with_feedback (which appends the stage-tagged
    feedback to history) with run_replanner_turn injected — a scoped agent with
    the planner's read-only pull tools (list_primitives / lookup_primitive / KB /
    design_reference) but WITHOUT delegate_features (no forking; a replan edits
    one existing plan, it never decomposes a new assembly).

    The pull tools are HTTP clients to the backend; this activity runs in the
    WORKER container, so we resolve the backend URL from the worker's own
    BACKEND_URL env (e.g. http://backend:8001) — NOT inp.backend_url, which is the
    backend container's self-view (localhost:8001) and unreachable from here.
    """
    import os

    try:
        last_plan = PrimitivePlan.model_validate(inp.last_plan_dict)
        backend_url = os.environ.get("BACKEND_URL") or inp.backend_url

        def planner_fn(original_prompt: str, history: list[dict[str, str]]):  # noqa: ANN202
            return run_replanner_turn(original_prompt, history, backend_url=backend_url)

        with _heartbeating():
            out = replan_with_feedback(
                original_prompt=inp.original_prompt,
                last_plan=last_plan,
                failure_stage=inp.failure_stage,
                detail=inp.detail,
                prior_history=inp.history,
                planner_fn=planner_fn,
            )
        return ReplanOutput(ok=True, plan_dict=plan_to_dict(out))
    except Exception as exc:
        # run_replanner_turn no longer catches its own failures (no ask_user
        # fallback) — budget exhaustion, no FINAL emitted, or a schema mismatch
        # fast-rlm's retry loop couldn't resolve all land here. Never let an
        # uncaught exception crash the Temporal workflow — return ok=False so
        # the workflow surfaces a clean categorized "failed" result instead.
        logger.exception("replan_activity failed")
        return ReplanOutput(ok=False, error=str(exc))


@activity.defn
def record_trace_activity(inp: TraceInput) -> None:
    """Write the auditable trace.json for the final outcome (the artifact-store record).

    Non-success outcomes carry one of the six canonical failure categories, so the
    "0 silent geometry failures" gate holds (PRD §14).
    """
    failure_category = None if inp.status == "success" else category_for_stage(inp.failure_stage)
    trace = build_trace(
        run_id=inp.run_id,
        prompt=inp.prompt,
        plan=inp.plan_dict or None,
        code=inp.code or None,
        execution_result=inp.execution_result or None,
        mesh_report=inp.mesh_report or None,
        renders=inp.renders or None,
        verdict=inp.verdict or None,
        status=inp.status,
        attempts=inp.attempts,
        failure_category=failure_category,
        failure_detail=inp.failure_detail or None,
    )
    write_trace(trace)
