"""
test_validation_and_placement.py — the fixes from the office-chair run.

Covers (no LLM needed):
  1. validate_plan oracle: accepts valid primitive/custom plans, REJECTS invented
     primitive types (e.g. 'rounded_box') and bad params, and returns the list of
     valid primitive types so the model can self-correct.
  2. placement convention: position (local) THEN rotation (about origin) makes a
     radial pattern (5-star base) actually splay and stay one connected solid.

Run:  python tests/test_validation_and_placement.py
"""
import sys
from pathlib import Path
import os
os.environ["GEOMETRY_PLANNING_TEST"] = "true"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))

from schemas.geometry_plan import GeometryPlan, PRIMITIVES_REGISTRY
import kernel
import verify

VALID_TYPES = sorted(list(PRIMITIVES_REGISTRY.keys()) + ["custom"])
BASE = {"title": "t", "overall_dimensions": {"width": 40, "length": 20, "height": 10},
        "engineering_requirements": {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []},
        "assumptions": ["x"], "clarifications": []}


def valid(plan):
    try:
        GeometryPlan(**plan); return True
    except Exception:
        return False


def P(seq):
    return {**BASE, "primitives_sequence": seq}


def main():
    ok = 0; total = 0

    def check(label, cond):
        nonlocal ok, total
        total += 1; ok += bool(cond)
        print(f"  [{'OK ' if cond else '!! '}] {label}")

    print("=== 1. validate_plan oracle ===")
    check("valid box accepted",
          valid(P([{"sequence_id": 1, "name": "b", "primitive_type": "box", "parameters": {"length": 40, "width": 20, "height": 10}, "operation": "new", "rationale": "the base plate body of the part"}])))
    check("INVENTED 'rounded_box' rejected",
          not valid(P([{"sequence_id": 1, "name": "b", "primitive_type": "rounded_box", "parameters": {"width": 5, "length": 5, "height": 5, "radius": 1}, "operation": "new", "rationale": "a rounded cushion body for the seat"}])))
    check("extra param rejected",
          not valid(P([{"sequence_id": 1, "name": "b", "primitive_type": "box", "parameters": {"length": 40, "width": 20, "height": 10, "radius": 3}, "operation": "new", "rationale": "the base plate body of the part"}])))
    check("valid custom accepted",
          valid(P([{"sequence_id": 1, "name": "c", "primitive_type": "custom", "operation": "new", "rationale": "no primitive fits this organic shape", "parameters": {"shape_description": "x", "cadquery_operations": ["Workplane.revolve"], "code_sketch": "result=cq.Workplane('XZ').rect(2,2).revolve()", "declared_dimensions": {}}}])))
    check("'filleted_box' offered as a real alternative", "filleted_box" in VALID_TYPES and "rounded_box" not in VALID_TYPES)

    print("\n=== 2. placement convention (radial 5-star base) ===")
    steps = [{"sequence_id": 1, "name": "hub", "primitive_type": "cylinder", "parameters": {"radius": 30, "height": 50}, "operation": "new", "position": [0, 0, 25], "rationale": "central hub of the five-star base"}]
    for i in range(5):
        steps.append({"sequence_id": 2 + i, "name": f"leg{i}", "primitive_type": "box",
                      "parameters": {"length": 300, "width": 40, "height": 30}, "operation": "join",
                      "position": [150, 0, 15], "rotation": [0, 0, i * 72],
                      "rationale": f"radial leg number {i} of the five star base"})
    plan = P(steps)
    plan["overall_dimensions"] = {"width": 360, "length": 360, "height": 50}
    check("radial base plan validates", valid(plan))
    r = kernel.build_plan(plan)
    check("radial base builds", r["ok"])
    if r["ok"]:
        m = verify.measure(verify.cq_to_meshlib(r["solid"]))
        check("legs splay out (bbox > 500mm in X and Y, not stacked)", m["bbox"][0] > 500 and m["bbox"][1] > 500)
        check("base is ONE connected solid", m["components"] == 1)

    print(f"\n{ok}/{total} checks passed", "\u2713" if ok == total else "\u2717")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
