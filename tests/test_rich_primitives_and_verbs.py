"""
test_rich_primitives_and_verbs.py — proves the rich certified vocabulary (Part 1) and the
composable shaping verbs (Part 2) build and validate deterministically, with no freehand code.

Covers:
  - EVERY primitive in primitives.json builds (defaults) -> positive volume, no exception.
  - representative non-default builds of the new structural/mechanical/contour primitives.
  - modifier verbs fillet/chamfer/shell refine the running solid; too-large / no-prior -> clean error.
  - a refined mini-assembly (lofted_box seat + filleted backrest, mated) is coherent + sound.
  - schema accepts modifier + list-param (profile/path) steps; sanity validators reject bad params.
"""

import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))
os.environ["PRIMITIVES_JSON_DATA"] = (ROOT / "schemas" / "primitives.json").read_text()

import cadquery as cq                       # noqa: E402
import kernel                               # noqa: E402
import verify as verify_mod                 # noqa: E402
from schemas.geometry_plan import GeometryPlan, PRIMITIVES_REGISTRY, MODIFIER_TYPES  # noqa: E402

_PRIMS = json.loads(os.environ["PRIMITIVES_JSON_DATA"])


def _plan(seq, kind="single_solid"):
    return {"title": "t", "assembly_kind": kind,
            "overall_dimensions": {"width": 1, "length": 1, "height": 1},
            "engineering_requirements": {"functional": [], "environmental_thermal": [],
                                         "structural": [], "manufacturing_cost": []},
            "assumptions": [], "clarifications": [], "primitives_sequence": seq}


def test_every_primitive_builds_with_defaults():
    bad = []
    for name in _PRIMS:
        try:
            wp = kernel._as_wp(kernel._primitive_solid(name, {}))
            if wp.val().Volume() <= 0:
                bad.append((name, "non-positive volume"))
        except Exception as e:
            bad.append((name, f"{type(e).__name__}: {e}"))
    assert not bad, f"primitives failed to build: {bad}"
    print(f"OK: all {len(_PRIMS)} primitives build with defaults (positive volume)")


def test_new_primitives_nondefault():
    cases = {
        "i_beam": {"flange_width": 50, "web_height": 80, "length": 200},
        "c_channel": {"width": 40, "height": 60, "thickness": 4, "length": 150},
        "hex_bolt_blank": {"head_flat_to_flat": 16, "shank_diameter": 8, "shank_length": 30},
        "circular_flange": {"outer_diameter": 60, "bolt_circle_diameter": 45, "num_bolt_holes": 8},
        "pipe": {"outer_diameter": 30, "wall_thickness": 3, "length": 100},
        "dome": {"radius": 25},
        "lofted_box": {"bottom_width": 500, "bottom_length": 480, "top_width": 460, "top_length": 440, "height": 60},
        "revolved_profile": {"profile": [[20, 0], [25, 10], [10, 60], [6, 80]]},
        "swept_circle": {"radius": 6, "path": [[0, 0, 0], [0, 0, 40], [30, 0, 60]]},
    }
    for name, params in cases.items():
        wp = kernel._as_wp(kernel._primitive_solid(name, params))
        assert wp.val().Volume() > 0, f"{name} non-positive volume"
    print(f"OK: {len(cases)} new primitives build with non-default params")


def test_fillet_modifier_rounds():
    box_v = cq.Workplane("XY").box(40, 40, 40).val().Volume()
    p = _plan([
        {"sequence_id": 1, "name": "b", "primitive_type": "box",
         "parameters": {"length": 40, "width": 40, "height": 40}, "operation": "new", "rationale": "block to round its sharp edges"},
        {"sequence_id": 2, "name": "r", "primitive_type": "fillet",
         "parameters": {"radius": 6, "edges": "all"}, "rationale": "round all edges of the body"},
    ])
    GeometryPlan(**p)  # schema accepts the modifier
    r = kernel.build_plan(p)
    assert r["ok"], r
    assert 0 < r["solid"].val().Volume() < box_v, "fillet should reduce volume (rounded edges)"
    print("OK: fillet modifier rounds the running solid (schema + build)")


def test_shell_modifier_hollows():
    box_v = cq.Workplane("XY").box(40, 40, 40).val().Volume()
    p = _plan([
        {"sequence_id": 1, "name": "b", "primitive_type": "box",
         "parameters": {"length": 40, "width": 40, "height": 40}, "operation": "new", "rationale": "block to hollow into a shell"},
        {"sequence_id": 2, "name": "h", "primitive_type": "shell",
         "parameters": {"thickness": 3, "face": "top"}, "rationale": "hollow to a shell"},
    ])
    GeometryPlan(**p)
    r = kernel.build_plan(p)
    assert r["ok"] and 0 < r["solid"].val().Volume() < box_v * 0.6, "shell should hollow the solid"
    print("OK: shell modifier hollows the running solid")


def test_modifier_errors_are_clean():
    too_big = _plan([
        {"sequence_id": 1, "name": "b", "primitive_type": "box",
         "parameters": {"length": 10, "width": 10, "height": 10}, "operation": "new", "rationale": "a small base block here"},
        {"sequence_id": 2, "name": "r", "primitive_type": "fillet",
         "parameters": {"radius": 50, "edges": "all"}, "rationale": "impossible huge fillet"},
    ])
    r = kernel.build_plan(too_big)
    assert not r["ok"] and r.get("error"), "too-large fillet must fail with a clean error"
    no_prior = _plan([
        {"sequence_id": 1, "name": "r", "primitive_type": "fillet",
         "parameters": {"radius": 2, "edges": "all"}, "rationale": "fillet with nothing before it"},
    ])
    r2 = kernel.build_plan(no_prior)
    assert not r2["ok"] and "no prior solid" in str(r2.get("error", "")), r2
    print("OK: modifier failures (too-large, no-prior) return clean errors")


def test_list_param_schema_and_build():
    p = _plan([{"sequence_id": 1, "name": "v", "primitive_type": "revolved_profile",
                "parameters": {"profile": [[10, 0], [12, 5], [8, 30], [4, 40]]},
                "operation": "new", "rationale": "a turned vase profile"}])
    GeometryPlan(**p)
    r = kernel.build_plan(p)
    assert r["ok"] and r["solid"].val().Volume() > 0
    print("OK: list-param (revolved_profile) validated by schema and builds")


def test_sanity_validators_reject_bad_params():
    def rejects(seq):
        try:
            GeometryPlan(**_plan(seq))
            return False
        except Exception:
            return True
    assert rejects([{"sequence_id": 1, "name": "p", "primitive_type": "pipe",
                     "parameters": {"outer_diameter": 10, "wall_thickness": 6, "length": 20},
                     "operation": "new", "rationale": "bore vanishes: wall too thick"}])
    assert rejects([{"sequence_id": 1, "name": "f", "primitive_type": "circular_flange",
                     "parameters": {"outer_diameter": 20, "bolt_circle_diameter": 25},
                     "operation": "new", "rationale": "bolt circle outside the flange"}])
    print("OK: sanity validators reject bad pipe / flange params")


def test_refined_mini_assembly():
    # lofted_box seat (contoured) + a filleted backrest, mated -> one coherent, sound object.
    p = _plan([
        {"sequence_id": 1, "name": "seat", "part": "seat", "primitive_type": "lofted_box",
         "parameters": {"bottom_width": 400, "bottom_length": 400, "top_width": 380, "top_length": 380, "height": 50},
         "operation": "new", "position": [0, 0, 0], "rationale": "a contoured seat pan via loft"},
        {"sequence_id": 2, "name": "back", "part": "back", "primitive_type": "filleted_box",
         "parameters": {"length": 380, "width": 40, "height": 400, "fillet_val": 15},
         "operation": "new", "attach": {"to": "seat", "at": "back", "my_anchor": "front"},
         "rationale": "a rounded backrest mated to the seat"},
    ], kind="assembly")
    GeometryPlan(**p)
    r = kernel.build_plan(p)
    assert r["ok"], r
    rep = verify_mod.verify_solid(r["solid"], plan=p, part_solids=r["meta"].get("part_solids"))
    assert rep["verdict"] == "PASS", rep.get("localized_fix")
    print("OK: refined mini-assembly (lofted seat + filleted backrest) is coherent + sound")


def test_general_contour_primitives():
    # swept_profile: an arbitrary (rectangular) cross-section swept along a curved 3D path.
    sp = _plan([{"sequence_id": 1, "name": "rail", "primitive_type": "swept_profile",
                 "parameters": {"profile": [[-5, -2], [5, -2], [5, 2], [-5, 2]],
                                "path": [[0, 0, 0], [0, 0, 40], [15, 0, 60]]},
                 "operation": "new", "rationale": "a rectangular rail swept along a curved path"}])
    GeometryPlan(**sp)
    r = kernel.build_plan(sp)
    assert r["ok"] and r["solid"].val().Volume() > 0, r

    # lofted_sections: a contoured slab that narrows AND shifts between two arbitrary sections
    # (general loft — not box->box). Build + VERIFY it is sound.
    ls = _plan([{"sequence_id": 1, "name": "pan", "primitive_type": "lofted_sections",
                 "parameters": {"sections": [[0, -200, -200, 200, -200, 200, 200, -200, 200],
                                             [40, -160, -150, 160, -150, 160, 180, -160, 180]]},
                 "operation": "new", "rationale": "a contoured seat-pan slab via a general loft"}])
    GeometryPlan(**ls)
    r2 = kernel.build_plan(ls)
    assert r2["ok"], r2
    rep2 = verify_mod.verify_solid(r2["solid"], expected_components=1)
    assert rep2["verdict"] == "PASS", rep2.get("localized_fix")

    # revolved_profile with end_fillet: a turned body with rounded circular edges. Build + VERIFY.
    rp = _plan([{"sequence_id": 1, "name": "knob", "primitive_type": "revolved_profile",
                 "parameters": {"profile": [[20, 0], [25, 10], [10, 60], [6, 80]], "end_fillet": 2.0},
                 "operation": "new", "rationale": "a turned knob with rounded top/bottom edges"}])
    GeometryPlan(**rp)
    r3 = kernel.build_plan(rp)
    assert r3["ok"], r3
    rep3 = verify_mod.verify_solid(r3["solid"], expected_components=1)
    assert rep3["verdict"] == "PASS", rep3.get("localized_fix")
    print("OK: general contour primitives (swept_profile, lofted_sections, revolved_profile+end_fillet) build + verify")


def _run_all():
    fns = [test_every_primitive_builds_with_defaults, test_new_primitives_nondefault,
           test_general_contour_primitives,
           test_fillet_modifier_rounds, test_shell_modifier_hollows, test_modifier_errors_are_clean,
           test_list_param_schema_and_build, test_sanity_validators_reject_bad_params,
           test_refined_mini_assembly]
    for fn in fns:
        fn()
    print(f"\nALL {len(fns)} RICH-VOCABULARY TESTS PASSED")


if __name__ == "__main__":
    _run_all()
