"""Deterministic construction guards for single-part PrimitivePlans.

These run on the HOST (compile / FINAL accept / replan) — never rely on the LLM
to self-enforce. Illegal constructions fail fast with an actionable message so
the replanner REWRITES the construction tree, not just a dimension.
"""

from __future__ import annotations

from typing import Any

from runtime.schema import FinishOp, FinishStep, Operation, PrimitivePlan, PrimitiveStep

SHELL_THEN_UNION_MESSAGE = (
    "construction_error: shell-then-union is illegal on this platform. "
    "A solid was (or would be) unioned after a `shell` finish — that leaves a "
    "multi-shell / disconnected result. Hollow LAST: union ALL solid features "
    "first, then `shell` ONCE at the end; OR model a turned vessel as ONE "
    "`revolve` / `hollow_cylinder`. Removable caps are out of scope for a "
    "single solid — model the vessel body alone."
)

CAP_SECONDARY_BODY_MESSAGE = (
    "construction_error: cap/lid/plug as a separate union body is OUT OF SCOPE "
    "for single-part. Model ONE open vessel body only — prefer primitive "
    "`hollow_cylinder` or `revolve` (see design_reference open_vessel recipes). "
    "Do NOT union a second solid for a cap; do NOT retweak cap z by 1mm."
)

OPEN_VESSEL_ROOTS = frozenset({"hollow_cylinder", "revolve", "hollow_box"})
OPEN_VESSEL_FINISH_OPS = frozenset({FinishOp.fillet, FinishOp.chamfer})

# Deterministic intent → construction family (not an open LLM guess).
_VESSEL_KEYWORDS = (
    "bottle",
    "cup",
    "vase",
    "flask",
    "mug",
    "glass",
    "jar",
    "tumbler",
    "vessel",
    "beaker",
    "pitcher",
)
_PLATE_KEYWORDS = (
    "mounting plate",
    "base plate",
    "flange plate",
    "mount plate",
)

_CAP_ID_MARKERS = ("cap", "lid", "cover", "plug", "topper", "stopper")


def has_shell_then_union_dict(plan: dict[str, Any] | None) -> bool:
    """True if a `shell` finish step is followed later by a solid `union` step."""
    if not isinstance(plan, dict):
        return False
    seen_shell = False
    for step in plan.get("steps", []):
        if not isinstance(step, dict):
            continue
        if step.get("op") == "shell":
            seen_shell = True
        elif seen_shell and step.get("operation") == "union":
            return True
    return False


def has_shell_then_union_plan(plan: PrimitivePlan) -> bool:
    """Typed variant for compile-time checks on a validated PrimitivePlan."""
    seen_shell = False
    for step in plan.steps:
        if isinstance(step, FinishStep) and step.op is FinishOp.shell:
            seen_shell = True
        elif (
            isinstance(step, PrimitiveStep)
            and seen_shell
            and step.operation is Operation.union
        ):
            return True
    return False


def shell_then_union_error() -> str:
    """Stable error string for compile / preview / replan."""
    return SHELL_THEN_UNION_MESSAGE


def has_cap_style_secondary_body(plan: PrimitivePlan) -> bool:
    """True if a union step is clearly a cap/lid/plug second body (out of scope)."""
    for step in plan.steps:
        if not isinstance(step, PrimitiveStep):
            continue
        if step.operation is not Operation.union:
            continue
        sid = step.id.lower()
        if any(marker in sid for marker in _CAP_ID_MARKERS):
            return True
    return False


def has_union_after_cavity(plan: PrimitivePlan) -> bool:
    """True if a solid is unioned after a cut/shell that formed a cavity.

    The classic bottle+cap failure mode: hollow with cuts, then union cap.
    Free CSG may still do union-after-cut legitimately in free_csg; this flag
    is used for diagnosis and open_vessel enforcement.
    """
    seen_cavity = False
    for step in plan.steps:
        if isinstance(step, FinishStep) and step.op is FinishOp.shell:
            seen_cavity = True
        elif isinstance(step, PrimitiveStep):
            if step.operation is Operation.cut:
                seen_cavity = True
            elif seen_cavity and step.operation is Operation.union:
                return True
    return False


def classify_construction_family(prompt: str) -> str:
    """Map a user prompt to a construction family (deterministic keywords)."""
    text = (prompt or "").lower()
    if any(k in text for k in _VESSEL_KEYWORDS):
        return "open_vessel"
    if any(k in text for k in _PLATE_KEYWORDS):
        return "plate_like"
    return "free_csg"


def open_vessel_violations(plan: PrimitivePlan) -> list[str]:
    """Return errors if plan is not a legal single-body open vessel."""
    errors: list[str] = []
    prims = [s for s in plan.steps if isinstance(s, PrimitiveStep)]
    if not prims:
        return ["open_vessel: plan has no primitive steps"]
    base = prims[0]
    if base.primitive not in OPEN_VESSEL_ROOTS:
        errors.append(
            "construction_error: open_vessel requires a ONE-STEP hollow root "
            f"({', '.join(sorted(OPEN_VESSEL_ROOTS))}), got base primitive "
            f"'{base.primitive}'. Do NOT free-CSG a bottle with cylinder+cut+cap. "
            "Emit ONE hollow_cylinder or revolve for the vessel body only."
        )
    if len(prims) > 1:
        extra = ", ".join(f"{s.id}:{s.operation.value}/{s.primitive}" for s in prims[1:])
        errors.append(
            "construction_error: open_vessel forbids extra CSG bodies after the "
            f"root ({extra}). Cap/lid assemblies are out of scope — vessel body only."
        )
    for step in plan.steps:
        if isinstance(step, FinishStep):
            if step.op is FinishOp.shell:
                errors.append(
                    "construction_error: open_vessel root is already hollow — "
                    "do not apply a shell finish."
                )
            elif step.op not in OPEN_VESSEL_FINISH_OPS:
                errors.append(
                    f"construction_error: open_vessel only allows fillet/chamfer "
                    f"finish ops, got '{step.op.value}'."
                )
    return errors


def construction_errors_for_plan(
    plan: PrimitivePlan, *, family: str | None = None
) -> list[str]:
    """Host construction errors (always-on + optional family rules)."""
    errors: list[str] = []
    if has_shell_then_union_plan(plan):
        errors.append(SHELL_THEN_UNION_MESSAGE)
    if has_cap_style_secondary_body(plan):
        errors.append(CAP_SECONDARY_BODY_MESSAGE)
    # Family-specific: open_vessel is strict one-body.
    if family == "open_vessel":
        errors.extend(open_vessel_violations(plan))
    elif family is None and has_union_after_cavity(plan) and has_cap_style_secondary_body(plan):
        # Already covered by cap check; keep for clarity.
        pass
    return errors


def is_topology_failure_stage(stage: str) -> bool:
    """Stages where the construction tree is wrong, not a single parameter."""
    return stage in {
        "cadquery_execute",
        "mesh_repair",
        "cadquery_compile",
        "primitive_gap",
    }


def open_vessel_template_plan(
    *,
    part_name: str = "open_vessel",
    outer_radius: float = 35.0,
    height: float = 180.0,
    wall: float = 3.0,
) -> dict[str, Any]:
    """Deterministic legal vessel plan (no LLM) — hollow_cylinder body only.

    hollow_cylinder extrudes UP from position (base at z=position.z).
    """
    outer = max(float(outer_radius), 5.0)
    h = max(float(height), 10.0)
    inner = max(outer - max(float(wall), 1.0), outer * 0.5)
    return {
        "part_name": part_name or "open_vessel",
        "units": "mm",
        "steps": [
            {
                "id": "vessel_body",
                "primitive": "hollow_cylinder",
                "operation": "base",
                "parameters": {
                    "outer_radius": outer,
                    "inner_radius": inner,
                    "height": h,
                },
                "position": [0.0, 0.0, 0.0],
                "orientation": [0.0, 0.0, 0.0],
            }
        ],
    }


def extract_vessel_dims_from_plan(plan: dict[str, Any] | None) -> tuple[float, float]:
    """Best-effort (outer_radius, height) from a failed free-CSG vessel plan."""
    outer, height = 35.0, 180.0
    if not isinstance(plan, dict):
        return outer, height
    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if step.get("operation") != "base":
            continue
        params = step.get("parameters") or {}
        if "radius" in params:
            outer = float(params["radius"])
        if "outer_radius" in params:
            outer = float(params["outer_radius"])
        if "height" in params:
            height = float(params["height"])
        break
    return outer, height
