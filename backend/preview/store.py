"""Preview service — real-geometry evidence for a candidate PrimitivePlan.

The planner/replanner call this (via the preview_plan pull tool) to SEE a plan
before committing: does it compile, is it one watertight solid, how big is each
feature relative to the whole, and (optionally) a VLM critique of the render.

Reuses the existing pipeline pieces — the compiler, the CadQuery subprocess
runner, MeshLib inspection, the renderer, and the VLM judge — so there is no new
geometry engine and the preview reflects exactly what the real loop would build.
"""

from __future__ import annotations

from typing import Any

from runtime.compile_cadquery import CompileError
from runtime.preview import build_preview_script
from runtime.schema import PrimitivePlan, load_library


def _bbox_volume(size_mm: list[float]) -> float:
    """Axis-aligned bbox volume from a [dx, dy, dz] size, guarding zeros."""
    if not size_mm or len(size_mm) != 3:
        return 0.0
    dx, dy, dz = size_mm
    return float(dx) * float(dy) * float(dz)


def _annotate_per_feature(
    per_feature: list[dict[str, Any]], overall_bbox: dict[str, float] | None
) -> list[dict[str, Any]]:
    """Add pct_of_overall_bbox to each feature so scale reads at a glance."""
    overall = 0.0
    if overall_bbox:
        overall = (
            (overall_bbox["xmax"] - overall_bbox["xmin"])
            * (overall_bbox["ymax"] - overall_bbox["ymin"])
            * (overall_bbox["zmax"] - overall_bbox["zmin"])
        )
    for feat in per_feature:
        size = feat.get("size_mm")
        if size and overall > 0:
            feat["pct_of_overall_bbox"] = round(100.0 * _bbox_volume(size) / overall, 1)
    return per_feature


def preview_plan(
    plan_dict: dict[str, Any],
    feature_checklist: str = "",
    critique: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Compile + execute + inspect a plan and return structured evidence.

    Returns a dict with (keys absent when a stage didn't run):
      compiles, executes, error?, watertight, num_components, disconnected,
      disconnected_hint?, bbox, volume_mm3, num_faces, per_feature[], checklist,
      vlm_critique?.
    """
    from tools.artifacts import new_run_id, run_dir
    from tools.cq_exec import run_cadquery_script_json
    from tools.inspect_mesh import inspect_mesh

    evidence: dict[str, Any] = {"compiles": False, "executes": False}

    # 1. structural + library validation
    try:
        plan = PrimitivePlan.model_validate(plan_dict)
    except Exception as exc:  # noqa: BLE001 — a bad plan is a result, not a crash
        evidence["error"] = f"plan did not validate: {exc}"
        return evidence

    library = load_library()

    rid = run_id or new_run_id("preview")
    base = run_dir(rid)
    stl_path = str(base / "solid.stl")
    step_path = str(base / "solid.step")

    # 2. compile plan -> augmented preview script
    try:
        script = build_preview_script(plan, library, stl_path, step_path)
    except CompileError as exc:
        evidence["error"] = f"compile failed: {exc}"
        return evidence
    evidence["compiles"] = True

    # 3. run the geometry (subprocess isolated)
    result = run_cadquery_script_json(script)
    if not result.get("success"):
        evidence["error"] = str(result.get("error"))
        return evidence
    evidence["executes"] = True
    evidence["bbox"] = result.get("bbox")
    evidence["volume_mm3"] = result.get("volume")
    evidence["num_faces"] = result.get("faces_count")
    evidence["per_feature"] = _annotate_per_feature(
        result.get("per_feature") or [], result.get("bbox")
    )

    # 4. mesh inspection (watertight / components)
    mesh = inspect_mesh(stl_path)
    if mesh.get("success"):
        evidence["watertight"] = mesh.get("is_watertight")
        evidence["num_components"] = mesh.get("num_components")
        disconnected = (mesh.get("num_components") or 1) > 1
        evidence["disconnected"] = disconnected
        if disconnected:
            evidence["disconnected_hint"] = (
                f"{mesh.get('num_components')} disconnected components — features only "
                "TOUCH instead of overlapping. Extend each union feature ~0.5-1mm INTO "
                "the body it joins so the boolean fuses one watertight solid."
            )

    if feature_checklist.strip():
        evidence["checklist"] = feature_checklist.strip()

    # 5. optional VLM critique (render + judge) — expensive, off by default
    if critique:
        evidence["vlm_critique"] = _vlm_critique(plan, rid, stl_path, feature_checklist)

    return evidence


def _vlm_critique(
    plan: PrimitivePlan, run_id: str, stl_path: str, feature_checklist: str
) -> dict[str, Any]:
    """Render the previewed solid and run the grounded judge on it (best effort)."""
    from tools.render_views import render_views
    from tools.vlm_judge import judge_geometry_render

    renders = render_views(stl_path, run_id)
    if not renders.get("success"):
        return {"ran": False, "error": str(renders.get("error"))}
    verdict = judge_geometry_render(
        prompt=plan.part_name,
        render_png=renders.get("png_path", ""),
        feature_checklist=feature_checklist,
    )
    return {
        "ran": bool(verdict.get("verifier_ran")),
        "passed": verdict.get("passed"),
        "feedback": verdict.get("feedback"),
        "feature_findings": verdict.get("feature_findings"),
    }
