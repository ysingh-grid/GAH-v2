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

import json
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
    plan: PrimitivePlan,
    library: dict[str, Any],
    run_id: str,
    art: _Artifacts,
    *,
    prompt: str = "",
    feature_checklist: str = "",
    through_path: str | None = None,
) -> tuple[_StageFailure | None, PrimitivePlan]:
    """Compile -> execute -> optional host auto-hollow -> inspect/repair -> render.

    Returns (failure_or_None, plan_used). plan_used may gain host-synthesized
    cavity steps when through-path is required.
    """
    from tools.execute_cadquery import execute_cadquery
    from tools.inspect_mesh import inspect_mesh
    from tools.render_views import render_views
    from tools.repair_mesh import repair_mesh

    working = plan
    compile_failure = _compile_cadquery(working, library, art)
    if compile_failure is not None:
        return compile_failure, working

    art.execution_result = execute_cadquery(art.code, run_id)
    if not art.execution_result.get("success"):
        from runtime.replan import enrich_execute_failure_detail

        raw = str(art.execution_result.get("error") or "cadquery execute failed")
        return (
            _StageFailure(
                "cadquery_execute",
                enrich_execute_failure_detail(raw, working),
            ),
            working,
        )

    # Host owns hollow when through-path is required and plan is solid-only.
    working = _maybe_auto_hollow(
        working,
        library,
        run_id,
        art,
        prompt=prompt,
        feature_checklist=feature_checklist,
        through_path=through_path,
    )
    if not art.execution_result.get("success"):
        from runtime.replan import enrich_execute_failure_detail

        raw = str(art.execution_result.get("error") or "auto-hollow execute failed")
        return (
            _StageFailure(
                "cadquery_execute",
                enrich_execute_failure_detail(raw, working),
            ),
            working,
        )

    stl_path = art.execution_result["stl_path"]
    art.mesh_report = inspect_mesh(stl_path)
    if not art.mesh_report.get("passes"):
        repair = repair_mesh(stl_path, run_id)
        art.mesh_report = repair.get("after", art.mesh_report)
        if not repair.get("passes"):
            feedback_payload = dict(repair)
            feedback_payload["num_solids"] = art.execution_result.get("num_solids")
            feedback_payload["num_shells"] = art.execution_result.get("num_shells")
            return (
                _StageFailure(
                    "mesh_repair",
                    collect_feedback_detail(
                        "mesh_repair", feedback_payload, plan_to_dict(working)
                    ),
                ),
                working,
            )
        stl_path = repair["repaired_stl_path"]

    art.renders = render_views(stl_path, run_id)
    if not art.renders.get("success"):
        return (
            _StageFailure("cadquery_execute", str(art.renders.get("error"))),
            working,
        )
    return None, working


def _maybe_auto_hollow(
    plan: PrimitivePlan,
    library: dict[str, Any],
    run_id: str,
    art: _Artifacts,
    *,
    prompt: str,
    feature_checklist: str,
    through_path: str | None,
) -> PrimitivePlan:
    """If through-path required and plan is solid-only, synthesize cavity + re-exec."""
    from runtime.auto_hollow import synthesize_cavity_plan
    from runtime.metrics_gate import (
        plan_has_cavity_strategy,
        resolve_hollow_requirement,
    )
    from tools.execute_cadquery import execute_cadquery

    target = resolve_hollow_requirement(
        prompt, feature_checklist, plan, through_path=through_path
    )
    if not target.requires_hollow or plan_has_cavity_strategy(plan):
        return plan

    hollowed = synthesize_cavity_plan(plan, wall_mm=target.wall_mm)
    if hollowed is None:
        # Leave plan; host gate will raise hollow_missing with clear text.
        return plan

    compile_failure = _compile_cadquery(hollowed, library, art)
    if compile_failure is not None:
        return plan

    solid_volume = (art.execution_result or {}).get("volume")
    result = execute_cadquery(art.code, run_id)
    if not result.get("success"):
        # Keep solid execution_result for diagnosis; mark auto-hollow failed.
        art.execution_result = {
            **(art.execution_result or {}),
            "success": False,
            "error": (
                "CAUSE: hollow_synthesis_failed — host auto-cavity did not build "
                f"(wall_mm={target.wall_mm}). {result.get('error')}"
            ),
            "num_solids": result.get("num_solids"),
            "num_shells": result.get("num_shells"),
        }
        return hollowed

    # Topology must stay single-solid after auto-hollow.
    if result.get("num_solids", 1) != 1:
        art.execution_result = {
            **result,
            "success": False,
            "error": (
                "CAUSE: hollow_synthesis_failed — auto-cavity produced "
                f"{result.get('num_solids')} solids (need 1). Shrink wall or "
                "adjust outer/cavity overlap."
            ),
        }
        return hollowed

    # Cavity must remove real material — no-op cuts must not pass as hollow.
    hollow_vol = result.get("volume")
    if (
        solid_volume is not None
        and hollow_vol is not None
        and float(solid_volume) > 0
        and float(hollow_vol) >= 0.85 * float(solid_volume)
    ):
        art.execution_result = {
            **result,
            "success": False,
            "error": (
                "CAUSE: hollow_synthesis_failed — auto-cavity did not reduce volume "
                f"(solid_mm3={float(solid_volume):.1f} hollow_mm3={float(hollow_vol):.1f}; "
                "need <85% of solid). Cavity tools miss the body or wall_mm is wrong."
            ),
        }
        return hollowed

    art.execution_result = result
    return hollowed


def _run_host_intent_gates(
    prompt: str,
    plan: PrimitivePlan,
    art: _Artifacts,
    feature_checklist: str = "",
    through_path: str | None = None,
) -> _StageFailure | None:
    """Dimensional + hollow intent gates from measured geometry (no VLM)."""
    from runtime.metrics_gate import (
        check_envelope,
        check_hollow_intent,
        measured_from_execution,
        resolve_hollow_requirement,
    )

    target = resolve_hollow_requirement(
        prompt, feature_checklist, plan, through_path=through_path
    )
    hollow_err = check_hollow_intent(plan, target)
    if hollow_err:
        return _StageFailure("hollow_missing", hollow_err)
    measured = measured_from_execution(art.execution_result)
    if measured is None:
        return None
    dim_err = check_envelope(measured, target)
    if dim_err:
        return _StageFailure("dimensional_mismatch", dim_err)
    return None


def _enrich_detail_with_metrics(
    detail: str,
    prompt: str,
    art: _Artifacts,
    feature_checklist: str = "",
) -> str:
    """Append measured-vs-requested block so replan edits the right params."""
    from runtime.metrics_gate import (
        format_metrics_block,
        measured_from_execution,
        resolve_hollow_requirement,
    )

    target = resolve_hollow_requirement(prompt, feature_checklist, None)
    measured = measured_from_execution(art.execution_result)
    block = format_metrics_block(measured, target)
    if block in detail:
        return detail
    return f"{detail}\n\n{block}"


def _run_verify(
    prompt: str, plan_code: str, art: _Artifacts, feature_checklist: str = ""
) -> _StageFailure | None:
    """Run the multimodal verifier; returns a visual_mismatch failure or None."""
    from tools.verify_geometry import verify_geometry

    exec_result, mesh = art.execution_result, art.mesh_report
    if exec_result is None or mesh is None:
        raise RuntimeError("verifier ran before geometry produced results")
    metrics = _merge_metrics(exec_result, mesh)
    png = (art.renders or {}).get("png_path", "")
    art.verdict = verify_geometry(
        prompt,
        plan_code,
        metrics,
        png,
        prior_feedback=art.feedback_log or None,
        feature_checklist=feature_checklist,
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
    feature_checklist: str = "",
    through_path: str | None = None,
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
        feature_checklist: The required-feature checklist text (Task 2) used to
            ground the verifier per-feature; "" falls back to prompt-only judging.
        through_path: Optional session contract "required"|"none"|"unknown".

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
    # One deterministic open_vessel template recovery (no LLM) after first topology fail.
    vessel_template_used = False

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
            failure, plan = _run_geometry(
                plan,
                library,
                run_id,
                art,
                prompt=original_prompt,
                feature_checklist=feature_checklist,
                through_path=through_path,
            )
        # Host metric / hollow gates — measurable facts before VLM (saves judge cost
        # and gives replan structured numbers instead of prose-only).
        if failure is None:
            failure = _run_host_intent_gates(
                original_prompt,
                plan,
                art,
                feature_checklist,
                through_path=through_path,
            )
        if failure is None and verify:
            failure = _run_verify(original_prompt, art.code or "", art, feature_checklist)

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

        is_outer = failure.stage in ("visual_mismatch", "dimensional_mismatch")
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

        # Host template recovery for open_vessel topology fails — one shot, no LLM.
        # Stops the "nudge cap z by 1mm" thrash on bottle/cup prompts.
        recovered: PrimitivePlan | None = None
        try:
            from runtime.plan_guards import (
                classify_construction_family,
                extract_vessel_dims_from_plan,
                is_topology_failure_stage,
                open_vessel_template_plan,
            )
            from runtime.schema import accept_plan

            family = classify_construction_family(original_prompt)
            if (
                family == "open_vessel"
                and not vessel_template_used
                and is_topology_failure_stage(failure.stage)
            ):
                vessel_template_used = True
                outer, height = extract_vessel_dims_from_plan(plan_to_dict(plan))
                recovered = accept_plan(
                    open_vessel_template_plan(
                        part_name=plan.part_name or "open_vessel",
                        outer_radius=outer,
                        height=height,
                    )
                )
        except Exception:
            recovered = None

        try:
            if recovered is not None:
                new_plan = recovered
            else:
                # When shell_fail is active, mark the replan env so preview_plan
                # refuses plans that still carry a shell finish (host-enforced).
                import os

                from runtime.replan import is_shell_fail

                if is_shell_fail(failure.detail):
                    os.environ["DTCM_SHELL_FAIL"] = "1"
                replan_detail = _enrich_detail_with_metrics(
                    failure.detail, original_prompt, art, feature_checklist
                )
                new_plan = replan_with_feedback(
                    original_prompt=original_prompt,
                    last_plan=plan,
                    failure_stage=failure.stage,
                    detail=replan_detail,
                    prior_history=history,
                    planner_fn=planner_fn,
                )
                # No-op replan after HOST metric/construction failures: one forced
                # retry with hard reject. (Visual VLM failures may intentionally
                # return the same plan only for re-judge — those use reuse only
                # for verifier_error; for visual we re-run geometry.)
                if (
                    failure.stage
                    in {
                        "dimensional_mismatch",
                        "hollow_missing",
                        "mesh_repair",
                        "cadquery_execute",
                        "cadquery_compile",
                    }
                    and plan_to_dict(new_plan) == plan_to_dict(plan)
                ):
                    new_plan = replan_with_feedback(
                        original_prompt=original_prompt,
                        last_plan=plan,
                        failure_stage=failure.stage,
                        detail=(
                            "IDENTICAL PLAN REJECTED — your FINAL matched context["
                            "'current_plan'] byte-for-byte. You MUST change step "
                            "parameters/ids that affect the failure. Step ids in the "
                            "inventory must match exactly (do not invent new ids). "
                            f"Prior failure:\n{replan_detail[:900]}"
                        ),
                        prior_history=history,
                        planner_fn=planner_fn,
                    )
                if is_shell_fail(failure.detail):
                    os.environ.pop("DTCM_SHELL_FAIL", None)
            # Maintain STATE across plan->replan rounds AFTER this replan call so
            # the first replan only sees intake base (+ feedback inside replan),
            # and the second replan sees attempt 1 plan+result.
            # Compress history: short step summary + failure, not full plan JSON
            # (full dumps drove 90k+ prompt tokens on multi-replan runs).
            step_ids = [
                f"{s.get('id')}:{s.get('operation') or s.get('op')}"
                for s in plan_to_dict(plan).get("steps", [])
                if isinstance(s, dict)
            ]
            history.append({
                "role": "planner",
                "content": (
                    f"[attempt {attempts} plan] {plan.part_name} "
                    f"steps=[{', '.join(step_ids[:20])}]"
                ),
            })
            history.append({
                "role": "system",
                "content": (
                    f"[attempt {attempts} result] failed at stage "
                    f"'{failure.stage}': {failure.detail[:500]}"
                ),
            })
            # Keep only intake prefix + last 2 attempt pairs (4 messages) + room
            # for the next feedback message built inside replan_with_feedback.
            if len(history) > 12:
                # Preserve leading intake (non-attempt) messages, then tail.
                head = [m for m in history if "[attempt" not in m.get("content", "")]
                tail = [m for m in history if "[attempt" in m.get("content", "")][-4:]
                history = head + tail
            plan_unchanged = plan_to_dict(new_plan) == plan_to_dict(plan)
            # reuse_geometry only for verifier_error-style "plan ok, re-judge".
            # After visual/dimensional/hollow failure, identical plan must NOT
            # re-burn a verify cycle on the same STL (b90fc735 thrash).
            reuse_geometry = (
                recovered is None
                and geometry_was_ok
                and plan_unchanged
                and failure.stage == "verifier_error"
            )
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
