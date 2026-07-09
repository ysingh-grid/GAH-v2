"""Host metric / intent gates — measured geometry vs requested numbers.

General platform capability: CadQuery already reports bbox/volume. Use those
facts as hard acceptance criteria when the user stated numbers or hollow intent.
No product-name special cases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from runtime.schema import FinishOp, FinishStep, Operation, PrimitivePlan, PrimitiveStep


@dataclass(frozen=True)
class TargetMetrics:
    """Optional envelope targets extracted from prompt/checklist (mm)."""

    z_span: float | None = None  # overall height / extent along Z
    x_span: float | None = None
    y_span: float | None = None
    requires_hollow: bool = False
    wall_mm: float = 2.0


@dataclass(frozen=True)
class MeasuredMetrics:
    """Envelope measured from execution/mesh (mm)."""

    z_span: float
    x_span: float
    y_span: float
    volume_mm3: float | None = None


def extract_target_metrics(prompt: str, feature_checklist: str = "") -> TargetMetrics:
    """Pull conservative envelope targets from free text (prompt + checklist).

    Uses explicit Z=… anchors and clear hollow language. Does not invent dims.
    """
    text = f"{prompt or ''}\n{feature_checklist or ''}"
    z_vals = [float(z) for z in re.findall(r"\bZ\s*=\s*(-?\d+(?:\.\d+)?)", text, flags=re.I)]
    z_span: float | None = None
    if z_vals:
        z_span = max(z_vals) - min(z_vals)
        # Single "to Z=63" from origin → span 63
        if min(z_vals) >= 0 and max(z_vals) == z_span:
            pass
        elif min(z_vals) >= 0:
            z_span = max(z_vals)  # treat max Z as height from base at 0
    # Also: "total height of 63mm" / "63mm tall"
    if z_span is None:
        m = re.search(
            r"(?:total\s+)?(?:height|tall(?:ness)?)\s*(?:of\s+|is\s+)?(\d+(?:\.\d+)?)\s*mm",
            text,
            flags=re.I,
        )
        if m:
            z_span = float(m.group(1))
    requires_hollow = bool(
        re.search(
            r"\b("
            r"hollow|hollowed|through[- ]?(?:hole|path|bore|opening)|"
            r"open\s+and\s+hollow|open\s+top|internal\s+cavity|wall\s+thickness|"
            r"pipe|tube|duct|funnel|nozzle|conduit|passage|channel|"
            r"fluid|airflow|flow\s+path|cored|walled"
            r")\b",
            text,
            flags=re.I,
        )
    )
    wall_mm = 2.0
    wm = re.search(
        r"wall(?:\s+thickness)?\s*(?:of\s+|=\s*)?(\d+(?:\.\d+)?)\s*mm",
        text,
        flags=re.I,
    )
    if wm:
        wall_mm = max(float(wm.group(1)), 0.5)
    return TargetMetrics(
        z_span=z_span, requires_hollow=requires_hollow, wall_mm=wall_mm
    )


def resolve_hollow_requirement(
    prompt: str,
    feature_checklist: str = "",
    plan: PrimitivePlan | None = None,
    *,
    through_path: str | None = None,
) -> TargetMetrics:
    """Merge text extraction with optional session through_path + plan structure.

    through_path: "required" | "none" | "unknown" | None (use heuristics).
    Structural cue: plan uses loft/transition/hollow primitives that imply a passage
    (not product-name matching).
    """
    base = extract_target_metrics(prompt, feature_checklist)
    if through_path == "required":
        return TargetMetrics(
            z_span=base.z_span,
            x_span=base.x_span,
            y_span=base.y_span,
            requires_hollow=True,
            wall_mm=base.wall_mm,
        )
    if through_path == "none":
        return TargetMetrics(
            z_span=base.z_span,
            x_span=base.x_span,
            y_span=base.y_span,
            requires_hollow=False,
            wall_mm=base.wall_mm,
        )
    # unknown / None: text OR structural plan cue
    if base.requires_hollow:
        return base
    if plan is not None:
        from runtime.auto_hollow import plan_implies_through_path

        if plan_implies_through_path(plan) and not plan_has_cavity_strategy(plan):
            # Outer fitting-style solid with no cavity yet → host will hollow.
            return TargetMetrics(
                z_span=base.z_span,
                x_span=base.x_span,
                y_span=base.y_span,
                requires_hollow=True,
                wall_mm=base.wall_mm,
            )
    return base


def measured_from_execution(execution_result: dict[str, Any] | None) -> MeasuredMetrics | None:
    """Build MeasuredMetrics from execute_cadquery result bbox."""
    if not execution_result or not execution_result.get("success"):
        return None
    bbox = execution_result.get("bbox") or {}
    try:
        dx = float(bbox["xmax"]) - float(bbox["xmin"])
        dy = float(bbox["ymax"]) - float(bbox["ymin"])
        dz = float(bbox["zmax"]) - float(bbox["zmin"])
    except (KeyError, TypeError, ValueError):
        return None
    vol = execution_result.get("volume")
    return MeasuredMetrics(
        z_span=abs(dz),
        x_span=abs(dx),
        y_span=abs(dy),
        volume_mm3=float(vol) if vol is not None else None,
    )


def plan_has_cavity_strategy(plan: PrimitivePlan) -> bool:
    """True if the plan expresses a hollow via cut(s) or shell finish."""
    for step in plan.steps:
        if isinstance(step, PrimitiveStep) and step.operation is Operation.cut:
            return True
        if isinstance(step, FinishStep) and step.op is FinishOp.shell:
            return True
    return False


def check_envelope(
    measured: MeasuredMetrics,
    target: TargetMetrics,
    *,
    rel_tol: float = 0.12,
    abs_tol_mm: float = 3.0,
) -> str | None:
    """Return failure detail if envelope mismatches, else None.

    Tol: max(abs_tol_mm, rel_tol * requested) so both small and large parts work.
    """
    if target.z_span is None or target.z_span <= 0:
        return None
    tol = max(abs_tol_mm, rel_tol * target.z_span)
    err = abs(measured.z_span - target.z_span)
    if err <= tol:
        return None
    return (
        f"CAUSE: dimensional_mismatch — measured_height_mm={measured.z_span:.2f} "
        f"requested_height_mm={target.z_span:.2f} (tol={tol:.2f}mm). "
        f"measured_bbox_mm={{dx:{measured.x_span:.2f}, dy:{measured.y_span:.2f}, "
        f"dz:{measured.z_span:.2f}}}. "
        "Edit the plan step parameters/positions that control overall height "
        "(step ids must match the inventory exactly). Do NOT re-FINAL an identical plan."
    )


def check_hollow_intent(plan: PrimitivePlan, target: TargetMetrics) -> str | None:
    """If hollow was requested but plan has no cavity strategy, fail host-side."""
    if not target.requires_hollow:
        return None
    if plan_has_cavity_strategy(plan):
        return None
    return (
        "CAUSE: hollow_missing — prompt requires open/hollow/through path, but the "
        "plan has no cut steps and no shell finish (solid fill only). Add cavity "
        "cut solids (inner offsets of the body; compiler fuses all cuts into one "
        "tool) or a shell finish. Do NOT claim hollow without cavity operations."
    )


def check_hollow_volume(
    measured: MeasuredMetrics,
    target: TargetMetrics,
    *,
    solid_volume_mm3: float | None = None,
) -> str | None:
    """If through-path required and we know solid-fill volume, demand real removal.

    Compares measured volume to the pre-cavity solid volume when available.
    Without a solid baseline, only plan cavity strategy is enforced elsewhere.
    """
    if not target.requires_hollow:
        return None
    if solid_volume_mm3 is None or measured.volume_mm3 is None:
        return None
    if solid_volume_mm3 <= 0:
        return None
    if measured.volume_mm3 < 0.85 * solid_volume_mm3:
        return None
    return (
        "CAUSE: hollow_missing — through-path required but measured volume is still "
        f"solid-fill (measured_mm3={measured.volume_mm3:.1f} "
        f"solid_ref_mm3={solid_volume_mm3:.1f}). Cavity cuts must remove material "
        "(target <85% of solid fill)."
    )


def format_metrics_block(
    measured: MeasuredMetrics | None,
    target: TargetMetrics,
) -> str:
    """Structured measured-vs-requested block for replan feedback."""
    lines = ["=== MEASURED VS REQUESTED (host metrics) ==="]
    if measured:
        lines.append(
            f"measured_bbox_mm: dx={measured.x_span:.2f} dy={measured.y_span:.2f} "
            f"dz={measured.z_span:.2f}"
        )
        if measured.volume_mm3 is not None:
            lines.append(f"measured_volume_mm3: {measured.volume_mm3:.2f}")
    else:
        lines.append("measured_bbox_mm: (unavailable)")
    if target.z_span is not None:
        lines.append(f"requested_height_mm: {target.z_span:.2f}")
    if target.requires_hollow:
        lines.append("requested_hollow: true")
    lines.append(
        "Edit step params that control these metrics; step ids must match inventory."
    )
    return "\n".join(lines)
