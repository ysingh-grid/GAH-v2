"""
Flush, shape-agnostic anchors (deterministic): `_anchor_point` derives face/edge/corner anchors
from the part's BOUNDING BOX, so `at:'top'/my_anchor:'bottom'` lands FLUSH for ANY primitive and
ANY rotation. Previously anchors used BREP face selectors (exact for boxes/cylinders, unreliable for
swept/lofted/revolved/rotated parts), which left gaps and pushed the agent into hand-computed
center-to-center offsets — the behavioral root of the imprecise placement.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))
os.environ.setdefault("PRIMITIVES_JSON_DATA", (ROOT / "schemas" / "primitives.json").read_text())

import kernel                       # noqa: E402
import verify as verify_mod         # noqa: E402


def _reqs():
    return {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []}


def _asm(parts, w=120, l=120, h=120):
    return {"title": "flush", "assembly_kind": "assembly",
            "overall_dimensions": {"width": w, "length": l, "height": h},
            "engineering_requirements": _reqs(), "assumptions": [], "clarifications": [],
            "primitives_sequence": parts}


def test_curved_and_rotated_parts_mate_flush_without_offsets():
    plan = _asm([
        {"sequence_id": 1, "name": "base", "part": "base", "primitive_type": "box",
         "parameters": {"length": 60, "width": 60, "height": 20}, "operation": "new",
         "position": [0, 0, 0], "rationale": "the flat base the other parts mate onto"},
        # a CURVED swept rod, mated bottom-onto-base-top, slid +X across the face (in-plane)
        {"sequence_id": 2, "name": "rod", "part": "rod", "primitive_type": "swept_circle",
         "parameters": {"radius": 3.0, "path": [[0, 0, 0], [0, 0, 30]]}, "operation": "new",
         "attach": {"to": "base", "at": "top", "my_anchor": "bottom", "offset": [18, 0, 0]},
         "rationale": "a curved rod that must sit FLUSH on the base top via bbox anchors"},
        # a ROTATED lofted block, mated bottom-onto-base-top, slid -X across the face (in-plane)
        {"sequence_id": 3, "name": "blk", "part": "blk", "primitive_type": "lofted_box",
         "parameters": {"bottom_width": 16, "bottom_length": 16, "top_width": 12,
                        "top_length": 12, "height": 30}, "operation": "new",
         "rotation": [25, 0, 0],
         "attach": {"to": "base", "at": "top", "my_anchor": "bottom", "offset": [-18, 0, 0]},
         "rationale": "a rotated lofted block that must sit FLUSH on the base top via bbox anchors"},
    ])
    res = kernel.build_plan(plan)
    assert res["ok"], res
    # bbox anchors should land BOTH parts flush on the base top with NO large snap correction
    # (a large snap would mean the anchor left a gap — the old BREP-face behavior).
    big = [s for s in (res["meta"].get("snapped") or []) if s["moved_mm"] > 0.5]
    assert not big, f"flush bbox-anchors should need no large snap, got {res['meta'].get('snapped')}"
    rep = verify_mod.verify_solid(res["solid"], plan=plan, part_solids=res["meta"]["part_solids"])
    assert rep["verdict"] == "PASS", f"flush-mated assembly must pass: {rep.get('localized_fix')}"
    assert rep["coherence"]["num_clusters"] == 1, rep["coherence"]
    assert not rep["coherence"]["interpenetrations"], rep["coherence"]["interpenetrations"]
    print("PASS swept_circle + rotated lofted_box mate FLUSH on a box (no hand offsets, no snap, no burial)")


def test_anchor_point_is_bbox_extreme_for_rotated_part():
    # Direct unit check: after a rotation the 'top' anchor must be the world bbox zmax (not a BREP
    # face centroid that drifts under rotation).
    import cadquery as cq
    wp = cq.Workplane("XY").box(20, 20, 40).rotate((0, 0, 0), (1, 0, 0), 20)
    bb = wp.val().BoundingBox()
    ax, ay, az = kernel._anchor_point(wp, "top")
    assert abs(az - bb.zmax) < 1e-6, (az, bb.zmax)
    assert abs(ax - (bb.xmin + bb.xmax) / 2.0) < 1e-6, ax
    bx, by, bz = kernel._anchor_point(wp, "bottom")
    assert abs(bz - bb.zmin) < 1e-6, (bz, bb.zmin)
    print("PASS _anchor_point returns the bbox extreme (flush) for a rotated part")


if __name__ == "__main__":
    test_curved_and_rotated_parts_mate_flush_without_offsets()
    test_anchor_point_is_bbox_extreme_for_rotated_part()
    print("\nALL flush-anchor tests passed.")
