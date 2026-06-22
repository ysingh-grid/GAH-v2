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
  replan_activity    — no-tools replanner fixes the plan from a failure -> ReplanOutput
  record_trace_activity — write the auditable trace.json (artifact store)

Timeouts and retry policy live on the workflow side, not here.
"""

from __future__ import annotations

from temporalio import activity

# Pure single-attempt helpers shared with the in-process loop (runtime is the
# canonical, Temporal-free home of stage logic; temporal/ depends on runtime/).
from runtime.loop import _Artifacts, _run_geometry, _run_verify
from runtime.planner import run_replanner_turn
from runtime.replan import replan_with_feedback
from runtime.schema import PrimitivePlan, load_library, plan_to_dict
from runtime.trace import build_trace, category_for_stage, write_trace
from temporal.shared import (
    GenerateInput,
    GenerateOutput,
    ReplanInput,
    ReplanOutput,
    TraceInput,
    VerifyInput,
    VerifyOutput,
)


@activity.defn
def generate_activity(inp: GenerateInput) -> GenerateOutput:
    """GENERATING: compile CadQuery + .forge.js in parallel, execute, inspect, repair, render.

    Reuses runtime.loop._run_geometry (which calls _compile_parallel — both
    compilers run in a 2-thread pool). A failure in any sub-step (compile, execute,
    mesh repair, forge compile) comes back as a tagged GenerateOutput the workflow
    routes to the replanner.
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
        forge_js=art.forge_js or "",
        execution_result=art.execution_result or {},
        mesh_report=art.mesh_report or {},
        renders=art.renders or {},
    )


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

    failure = _run_verify(inp.prompt, inp.code, art)

    return VerifyOutput(
        passed=failure is None,
        feedback="" if failure is None else failure.detail,
        verdict=art.verdict or {},
    )


@activity.defn
def replan_activity(inp: ReplanInput) -> ReplanOutput:
    """PLANNING (replan): fix the plan from the failure message via the no-tools replanner.

    Reuses runtime.replan.replan_with_feedback (which appends the stage-tagged
    feedback to history) with run_replanner_turn injected as the planner — so the
    replan is a single no-tools REPL step (no list_primitives/lookup/web_search),
    which is what keeps replans fast and avoids the tool-cascade timeout.
    """
    last_plan = PrimitivePlan.model_validate(inp.last_plan_dict)

    def planner_fn(original_prompt: str, history: list[dict[str, str]]):  # noqa: ANN202
        return run_replanner_turn(original_prompt, history)

    out = replan_with_feedback(
        original_prompt=inp.original_prompt,
        last_plan=last_plan,
        failure_stage=inp.failure_stage,
        detail=inp.detail,
        prior_history=inp.history,
        planner_fn=planner_fn,
    )

    if out.action == "ask_user":
        return ReplanOutput(action="ask_user", question=out.question or "")
    return ReplanOutput(action="plan_ready", plan_dict=plan_to_dict(out.plan))


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
