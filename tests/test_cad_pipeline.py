"""
test_cad_pipeline.py — prove the deterministic BUILD -> VERIFY -> RENDER pipeline.

No LLM involved. Confirms: primitive and freeform plans build and pass the fixed
MeshLib battery; a deliberately broken plan is CAUGHT (the verifier is real, not a
rubber stamp); rendering produces a PNG. The RLM's planning runs on your machine;
this proves the substrate the plan feeds into.

Run:  python tests/test_cad_pipeline.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))

import kernel
import verify
from render import render_solid
from schemas.geometry_plan import GeometryPlan

base = {"title": "t", "overall_dimensions": {"width": 40, "length": 20, "height": 10},
        "engineering_requirements": {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []},
        "assumptions": ["std"], "clarifications": []}


def run(name, seq, declared, expect_pass, expected_components=1, render=False):
    plan = {**base, "primitives_sequence": seq}
    GeometryPlan(**plan)  # planning contract holds
    b = kernel.build_plan(plan)
    if not b["ok"]:
        print(f"[{'OK ' if not expect_pass else '!! '}] {name}: BUILD FAILED at step {b.get('failed_step')}")
        return not expect_pass
    v = verify.verify_solid(b["solid"], declared_bbox=declared, expected_components=expected_components)
    ok = (v["verdict"] == "PASS") == expect_pass
    extra = ""
    if render and v["verdict"] == "PASS":
        out = render_solid(b["solid"], f"/tmp/{name}.png")
        extra = f" | rendered {Path(out).name}"
    print(f"[{'OK ' if ok else '!! '}] {name}: verdict={v['verdict']} (expected {'PASS' if expect_pass else 'FAIL'})"
          f" bbox={v['measurements']['bbox']} comp={v['measurements']['components']}{extra}")
    if v["verdict"] == "FAIL":
        print(f"         localized_fix: {v['localized_fix']}")
    return ok


def main():
    results = []
    # 1) primitive bracket -> PASS + render
    results.append(run("primitive_bracket", [
        {"sequence_id": 1, "primitive_type": "box", "parameters": {"length": 40, "width": 20, "height": 10}, "operation": "new", "rationale": "base plate body"},
        {"sequence_id": 2, "primitive_type": "cylinder", "parameters": {"radius": 3, "height": 12}, "operation": "cut", "position": [-10, 0, 0], "rationale": "left M6 clearance hole"},
        {"sequence_id": 3, "primitive_type": "cylinder", "parameters": {"radius": 3, "height": 12}, "operation": "cut", "position": [10, 0, 0], "rationale": "right M6 clearance hole"},
    ], declared=[40, 20, 10], expect_pass=True, render=True))

    # 2) freeform revolved bowl -> PASS + render
    results.append(run("freeform_bowl", [
        {"sequence_id": 1, "primitive_type": "custom", "operation": "new", "rationale": "revolved organic bowl, no primitive fits",
         "parameters": {"shape_description": "revolved bowl", "cadquery_operations": ["Workplane.revolve"],
                        "code_sketch": "result = cq.Workplane('XZ').moveTo(2,0).lineTo(20,0).lineTo(18,5).lineTo(3,5).lineTo(2,40).lineTo(0,40).lineTo(0,0).close().revolve(360,(0,0,0),(0,1,0))",
                        "declared_dimensions": {"height": 40}}},
    ], declared=None, expect_pass=True, render=True))

    # 3) BROKEN: union of two disjoint boxes -> ONE object, TWO components -> must FAIL
    results.append(run("broken_two_bodies", [
        {"sequence_id": 1, "primitive_type": "box", "parameters": {"length": 10, "width": 10, "height": 10}, "operation": "new", "rationale": "body one of the part"},
        {"sequence_id": 2, "primitive_type": "box", "parameters": {"length": 10, "width": 10, "height": 10}, "operation": "join", "position": [50, 0, 0], "rationale": "stray disconnected body unioned in"},
    ], declared=None, expect_pass=False, expected_components=1))

    # 4) bbox is an OUTPUT, not a gate: a sound box with a wildly-wrong DECLARED size still PASSES
    #    geometry (the overall extent is emergent/host-measured; size-vs-request is the fidelity
    #    critic's job, not the deterministic battery). Previously this FAILED on the bbox self-audit.
    results.append(run("bbox_is_output_not_gate", [
        {"sequence_id": 1, "primitive_type": "box", "parameters": {"length": 40, "width": 20, "height": 10}, "operation": "new", "rationale": "sound body; declared overall size is intentionally wrong"},
    ], declared=[100, 50, 25], expect_pass=True))

    ok = sum(results)
    print(f"\n{ok}/{len(results)} pipeline checks behaved as expected",
          "\u2713" if ok == len(results) else "\u2717")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
