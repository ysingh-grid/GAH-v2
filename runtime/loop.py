"""The pure geometry loop: plan -> solid -> mesh -> render -> verify -> repair.

This is the Temporal-free heart of the runtime (Q5). Given a validated
PrimitivePlan it compiles to CadQuery, executes it, inspects/repairs the mesh,
renders, and verifies; any stage failure routes back through the planner via
`replan_with_feedback`, bounded by the inner/outer caps. Every attempt ends in a
trace tagged with the 6-category taxonomy.

The planner is dependency-injected (`planner_fn`) so the whole loop is testable
with real geometry tools but no live RLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from runtime.compile_cadquery import CompileError, compile_plan_to_cadquery
from runtime.replan import (
    PlannerFn,
    collect_feedback_detail,
    is_exhausted,
    replan_with_feedback,
)
from runtime.schema import PrimitivePlan, plan_to_dict
from runtime.trace import FailureCategory, build_trace, category_for_stage, write_trace


@dataclass
class LoopResult:
    """Outcome of one geometry-loop run."""

    status: str  # "success" | "failed"
    run_id: str
    trace_path: str
    attempts: int
    final_plan: dict[str, Any]
    failure_category: str | None = None
    message: str = ""
    forge_js: str = ""  # emit artifact, compiled in parallel during generate


@dataclass
class _StageFailure:
    stage: str
    detail: str


@dataclass
class _Artifacts:
    """Mutable bag of per-attempt artifacts collected for the trace."""

    code: str | None = None
    forge_js: str | None = None  # .forge.js compiled in parallel with `code`
    execution_result: dict[str, Any] | None = None
    mesh_report: dict[str, Any] | None = None
    renders: dict[str, Any] | None = None
    verdict: dict[str, Any] | None = None
    feedback_log: list[str] = field(default_factory=list)


def _merge_metrics(execution_result: dict[str, Any], mesh_report: dict[str, Any]) -> dict[str, Any]:
    """Combine OCCT + MeshLib numbers into the dict the verifier reads."""
    return {
        "volume_mm3": execution_result.get("volume"),
        "bounding_box": execution_result.get("bbox"),
        "num_faces": execution_result.get("faces_count"),
        "is_watertight": mesh_report.get("is_watertight"),
        "is_valid": mesh_report.get("passes"),
        "open_holes": mesh_report.get("open_holes"),
        "self_intersections": mesh_report.get("self_intersections"),
        "num_components": mesh_report.get("num_components"),
    }

def _compile_cadquery(
    plan: PrimitivePlan, library: dict[str, Any], art: _Artifacts
) -> _StageFailure | None:
    """Compile plan to CadQuery Python script; routes failures back to replan."""
    try:
        art.code = compile_plan_to_cadquery(plan, library)
    except CompileError as exc:
        stage = "primitive_gap" if "primitive_gap" in str(exc) else "cadquery_compile"
        return _StageFailure(stage, str(exc))
    return None


def _run_geometry(
    plan: PrimitivePlan, library: dict[str, Any], run_id: str, art: _Artifacts
) -> _StageFailure | None:
    """Compile -> execute -> inspect/repair -> render. Returns a failure or None."""
    from tools.execute_cadquery import execute_cadquery
    from tools.inspect_mesh import inspect_mesh
    from tools.render_views import render_views
    from tools.repair_mesh import repair_mesh

    compile_failure = _compile_cadquery(plan, library, art)
    if compile_failure is not None:
        return compile_failure

    art.execution_result = execute_cadquery(art.code, run_id)
    if not art.execution_result.get("success"):
        return _StageFailure("cadquery_execute", str(art.execution_result.get("error")))

    stl_path = art.execution_result["stl_path"]
    art.mesh_report = inspect_mesh(stl_path)
    if not art.mesh_report.get("passes"):
        repair = repair_mesh(stl_path, run_id)
        art.mesh_report = repair.get("after", art.mesh_report)
        if not repair.get("passes"):
            return _StageFailure("mesh_repair", collect_feedback_detail("mesh_repair", repair))
        stl_path = repair["repaired_stl_path"]

    art.renders = render_views(stl_path, run_id)
    if not art.renders.get("success"):
        return _StageFailure("cadquery_execute", str(art.renders.get("error")))
    return None


def _run_verify(prompt: str, plan_code: str, art: _Artifacts) -> _StageFailure | None:
    """Run the multimodal verifier; returns a visual_mismatch failure or None."""
    from tools.verify_geometry import verify_geometry

    exec_result, mesh = art.execution_result, art.mesh_report
    if exec_result is None or mesh is None:
        raise RuntimeError("verifier ran before geometry produced results")
    metrics = _merge_metrics(exec_result, mesh)
    png = (art.renders or {}).get("png_path", "")
    art.verdict = verify_geometry(
        prompt, plan_code, metrics, png, prior_feedback=art.feedback_log or None
    )
    if not art.verdict.get("passed"):
        failure_stage = str(art.verdict.get("failure_stage") or "visual_mismatch")
        feedback = collect_feedback_detail(failure_stage, art.verdict)
        art.feedback_log.append(feedback)
        return _StageFailure(failure_stage, feedback)
    return None


def _finalize(
    *,
    run_id: str,
    prompt: str,
    plan: PrimitivePlan,
    art: _Artifacts,
    status: str,
    attempts: int,
    failure_category: FailureCategory | None,
    failure_detail: str | None,
    message: str,
) -> LoopResult:
    """Build + write the trace and return the LoopResult."""
    plan_dict = plan_to_dict(plan)
    trace = build_trace(
        run_id=run_id,
        prompt=prompt,
        plan=plan_dict,
        code=art.code,
        execution_result=art.execution_result,
        mesh_report=art.mesh_report,
        renders=art.renders,
        verdict=art.verdict,
        status=status,
        attempts=attempts,
        failure_category=failure_category,
        failure_detail=failure_detail,
    )
    trace_path = write_trace(trace)
    return LoopResult(
        status=status,
        run_id=run_id,
        trace_path=trace_path,
        attempts=attempts,
        final_plan=plan_dict,
        failure_category=failure_category.value if failure_category else None,
        message=message,
        forge_js=art.forge_js or "",
    )


def run_geometry_loop(
    *,
    original_prompt: str,
    initial_plan: PrimitivePlan,
    planner_fn: PlannerFn,
    library: dict[str, Any],
    run_id: str,
    verify: bool = True,
    history: list[dict[str, str]] | None = None,
) -> LoopResult:
    """Run the bounded plan->verify->repair loop, returning a traced outcome.

    Args:
        original_prompt: The user's request (for the verifier + replan context).
        initial_plan: The validated plan from the planner's plan_ready.
        planner_fn: Planner turn used for re-planning on failure (injected).
        library: Primitives library dict.
        run_id: Artifact run id (all outputs land in outputs/{run_id}/).
        verify: If False, skip the multimodal verifier (geometry-only runs).
        history: Conversation history to thread into replans.

    Returns:
        A LoopResult with status success | failed, always with a trace written
        and (on failure) a failure_category set.
    """
    plan = initial_plan
    art = _Artifacts()
    history = list(history or [])
    inner_attempts = 0
    outer_attempts = 0
    reuse_geometry = False  # replan returned the plan UNCHANGED after a verify-stage
    # failure (e.g. verifier_error) → the geometry on disk is still valid; skip the
    # full recompile→execute→inspect→render and go straight back to verify.

    while True:
        if reuse_geometry:
            reuse_geometry = False
            art = _Artifacts(
                code=art.code,
                forge_js=art.forge_js,
                execution_result=art.execution_result,
                mesh_report=art.mesh_report,
                renders=art.renders,
                feedback_log=art.feedback_log,
            )
            failure = None
        else:
            art = _Artifacts(feedback_log=art.feedback_log)
            failure = _run_geometry(plan, library, run_id, art)
        if failure is None and verify:
            failure = _run_verify(original_prompt, art.code or "", art)

        attempts = inner_attempts + outer_attempts + 1
        if failure is None:
            return _finalize(
                run_id=run_id,
                prompt=original_prompt,
                plan=plan,
                art=art,
                status="success",
                attempts=attempts,
                failure_category=None,
                failure_detail=None,
                message="verified" if verify else "geometry ok",
            )

        is_outer = failure.stage == "visual_mismatch"
        if is_outer:
            outer_attempts += 1
        else:
            inner_attempts += 1
        attempt_for_stage = outer_attempts if is_outer else inner_attempts
        category = category_for_stage(failure.stage)

        if is_exhausted(failure.stage, attempt_for_stage):
            return _finalize(
                run_id=run_id,
                prompt=original_prompt,
                plan=plan,
                art=art,
                status="failed",
                attempts=attempts,
                failure_category=category,
                failure_detail=failure.detail,
                message=f"exhausted attempts at stage '{failure.stage}'",
            )

        geometry_was_ok = art.renders is not None and bool(art.renders.get("success"))
        try:
            new_plan = replan_with_feedback(
                original_prompt=original_prompt,
                last_plan=plan,
                failure_stage=failure.stage,
                detail=failure.detail,
                prior_history=history,
                planner_fn=planner_fn,
            )
            # Record this round's failure COMPACTLY so the NEXT replan (if any)
            # knows what was already tried — replan_with_feedback embeds the full
            # current plan+detail itself, so history carries only the short prior-
            # attempt facts (bounded by the caps: <=8 short entries per run).
            history.append({
                "role": "system",
                "content": (
                    f"[prior attempt] failed at stage '{failure.stage}': "
                    f"{failure.detail[:500]}"
                ),
            })
            # Plan returned unchanged after a verify-stage failure → geometry on
            # disk is identical; skip regenerate and jump straight to re-verify.
            reuse_geometry = geometry_was_ok and plan_to_dict(new_plan) == plan_to_dict(plan)
            plan = new_plan
        except Exception as exc:
            return _finalize(
                run_id=run_id,
                prompt=original_prompt,
                plan=plan,
                art=art,
                status="failed",
                attempts=attempts,
                failure_category=category_for_stage("replan_error"),
                failure_detail=str(exc),
                message="replanner failed to produce a corrected plan",
            )
