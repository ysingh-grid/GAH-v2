"""Host automatic hollow — general wall-based cavity synthesis.

When through-path is required and the planner emitted only an outer solid tree,
the host synthesizes cavity cut steps by shrinking each additive primitive by
wall_mm, then the two-phase compiler fuses those cuts into one tool.

This is platform infrastructure (parameter shrink per primitive schema), not a
per-product recipe. Unknown primitives are skipped; if no cavity can be built,
caller gets None and should fail hollow_missing / hollow_synthesis_failed.
"""

from __future__ import annotations

from typing import Any

from runtime.schema import (
    Operation,
    PrimitivePlan,
    PrimitiveStep,
    FinishStep,
    plan_from_dict,
    plan_to_dict,
)


# Primitives that already encode a through-fitting / loft body and almost always
# need a passage when used as the main solid (structural cue, not product name).
THROUGH_PRIMITIVES = frozenset(
    {
        "rect_to_round",
        "rect_to_rect",
        "hollow_cylinder",
        "hollow_box",
        "tube",
        "pipe",
    }
)


def plan_implies_through_path(plan: PrimitivePlan) -> bool:
    """True if the construction tree uses primitives that imply a passage."""
    for step in plan.steps:
        if isinstance(step, PrimitiveStep) and step.primitive in THROUGH_PRIMITIVES:
            # hollow_* already is a cavity wall solid — still "through" intent
            return True
    return False


def _shrink_params(primitive: str, params: dict[str, Any], wall: float) -> dict[str, Any] | None:
    """Return shrunk parameters for a cavity tool, or None if not shrinkable."""
    p = dict(params)
    w = float(wall)
    if w <= 0:
        return None

    if primitive == "box":
        length = float(p.get("length", 10)) - 2 * w
        width = float(p.get("width", 10)) - 2 * w
        height = float(p.get("height", 10)) + 2 * w  # ensure through-thickness punch
        if length <= 0.5 or width <= 0.5:
            return None
        p["length"] = length
        p["width"] = width
        p["height"] = height
        return p

    if primitive == "cylinder":
        radius = float(p.get("radius", 5)) - w
        height = float(p.get("height", 10)) + 2 * w
        if radius <= 0.5:
            return None
        p["radius"] = radius
        p["height"] = height
        return p

    if primitive == "rect_to_round":
        bl = float(p.get("base_length", 40)) - 2 * w
        bw = float(p.get("base_width", 30)) - 2 * w
        td = float(p.get("top_diameter", 20)) - 2 * w
        if bl <= 0.5 or bw <= 0.5 or td <= 1.0:
            return None
        p["base_length"] = bl
        p["base_width"] = bw
        p["top_diameter"] = td
        # height unchanged — same axial span as outer loft
        return p

    if primitive == "rect_to_rect":
        bl = float(p.get("base_length", 40)) - 2 * w
        bw = float(p.get("base_width", 30)) - 2 * w
        tl = float(p.get("top_length", 20)) - 2 * w
        tw = float(p.get("top_width", 20)) - 2 * w
        if min(bl, bw, tl, tw) <= 0.5:
            return None
        p["base_length"] = bl
        p["base_width"] = bw
        p["top_length"] = tl
        p["top_width"] = tw
        return p

    if primitive in ("cone",):
        # cone uses base_diameter / top_diameter in library
        if "base_diameter" in p:
            bd = float(p["base_diameter"]) - 2 * w
            td = float(p.get("top_diameter", 0)) - 2 * w
            if bd <= 1.0:
                return None
            p["base_diameter"] = bd
            p["top_diameter"] = max(td, 0.0)
            p["height"] = float(p.get("height", 10)) + 2 * w
            return p
        return None

    if primitive in ("rounded_cylinder", "filleted_box", "chamfered_box"):
        # treat like cylinder/box core params if present
        if "radius" in p:
            return _shrink_params("cylinder", p, w)
        if "length" in p and "width" in p:
            return _shrink_params("box", p, w)
        return None

    # hollow_cylinder / hollow_box already walls — no extra cavity step
    if primitive in ("hollow_cylinder", "hollow_box"):
        return None

    return None


def _is_thin_plate_box(primitive: str, params: dict[str, Any]) -> bool:
    """True for flat plate solids (height << lateral size) — through-hole, not full shrink."""
    if primitive != "box":
        return False
    try:
        length = float(params.get("length", 10))
        width = float(params.get("width", 10))
        height = float(params.get("height", 10))
    except (TypeError, ValueError):
        return False
    return height > 0 and height < 0.25 * min(length, width)


def synthesize_cavity_plan(
    plan: PrimitivePlan,
    *,
    wall_mm: float = 2.0,
) -> PrimitivePlan | None:
    """Return a new plan with cavity cut steps derived from additive solids.

    Keeps finish steps. Skips additive steps that cannot shrink. Returns None if
    zero cavity cuts could be synthesized.

    Thin plate boxes (flanges) do not get a near-full-size shrink cut (that severs
    the rim). They get a through-hole matched to the largest subsequent cavity
    footprint so the plate stays one connected solid with a passage.
    """
    data = plan_to_dict(plan)
    new_steps: list[dict[str, Any]] = []
    cavity_steps: list[dict[str, Any]] = []
    thin_plates: list[dict[str, Any]] = []
    wall = max(float(wall_mm), 0.5)

    for step in data.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if "op" in step and "operation" not in step:
            new_steps.append(step)
            continue
        op = step.get("operation")
        if op in ("base", "union", "intersect"):
            new_steps.append(step)
            prim = step.get("primitive") or ""
            params = dict(step.get("parameters") or {})
            if _is_thin_plate_box(prim, params):
                thin_plates.append(step)
                continue
            shrunk = _shrink_params(prim, params, wall)
            if shrunk is None:
                continue
            pos = list(step.get("position") or [0.0, 0.0, 0.0])
            cavity_steps.append(
                {
                    "id": f"auto_cavity_{step.get('id', 'x')}",
                    "primitive": prim,
                    "operation": "cut",
                    "parameters": shrunk,
                    "position": pos,
                    "orientation": list(step.get("orientation") or [0.0, 0.0, 0.0]),
                }
            )
        elif op == "cut":
            new_steps.append(step)
        else:
            new_steps.append(step)

    # Through-holes in thin plates: match passage to first loft/cyl cavity footprint.
    passage_box: tuple[float, float] | None = None
    passage_r: float | None = None
    for cav in cavity_steps:
        prim = cav.get("primitive")
        params = cav.get("parameters") or {}
        if prim == "rect_to_round":
            passage_box = (
                float(params.get("base_length", 10)),
                float(params.get("base_width", 10)),
            )
            break
        if prim == "rect_to_rect":
            passage_box = (
                float(params.get("base_length", 10)),
                float(params.get("base_width", 10)),
            )
            break
        if prim == "cylinder" and passage_r is None:
            passage_r = float(params.get("radius", 5))

    for plate in thin_plates:
        params = dict(plate.get("parameters") or {})
        height = float(params.get("height", 3)) + 2.0
        pos = list(plate.get("position") or [0.0, 0.0, 0.0])
        if passage_box is not None:
            cavity_steps.insert(
                0,
                {
                    "id": f"auto_cavity_{plate.get('id', 'plate')}",
                    "primitive": "box",
                    "operation": "cut",
                    "parameters": {
                        "length": passage_box[0],
                        "width": passage_box[1],
                        "height": height,
                    },
                    "position": pos,
                    "orientation": list(plate.get("orientation") or [0.0, 0.0, 0.0]),
                },
            )
        elif passage_r is not None:
            cavity_steps.insert(
                0,
                {
                    "id": f"auto_cavity_{plate.get('id', 'plate')}",
                    "primitive": "cylinder",
                    "operation": "cut",
                    "parameters": {"radius": passage_r, "height": height},
                    "position": pos,
                    "orientation": list(plate.get("orientation") or [0.0, 0.0, 0.0]),
                },
            )

    if not cavity_steps:
        return None

    additive: list[dict[str, Any]] = []
    finishes: list[dict[str, Any]] = []
    existing_cuts: list[dict[str, Any]] = []
    for s in new_steps:
        if isinstance(s, dict) and s.get("op") and "operation" not in s:
            finishes.append(s)
        elif isinstance(s, dict) and s.get("operation") == "cut":
            existing_cuts.append(s)
        else:
            additive.append(s)

    merged = additive + existing_cuts + cavity_steps + finishes
    data["steps"] = merged
    try:
        return plan_from_dict(data)
    except Exception:
        return None
