"""
test_validation_boundaries.py — the schema is now a PURE geometry validator.

Confirms the legitimate validators still reject bad geometry, and that the
previously-bandaged cases (many repeated primitives, duplicate rationales, large
parts, assumptions-without-clarifications) are now correctly ACCEPTED. Real
assertions: exits non-zero on any mismatch.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from schemas.geometry_plan import GeometryPlan

BASE = {"title": "Boundary Test", "overall_dimensions": {"width": 60, "length": 40, "height": 10},
        "engineering_requirements": {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []},
        "assumptions": ["std"], "clarifications": []}

ok = 0; total = 0


def expect(name, seq, should_pass, override=None):
    global ok, total
    total += 1
    payload = {**BASE, "primitives_sequence": seq}
    if override:
        payload.update(override)
    try:
        GeometryPlan(**payload)
        passed = True
    except Exception:
        passed = False
    good = (passed == should_pass)
    ok += good
    verb = "accepted" if passed else "rejected"
    want = "accept" if should_pass else "reject"
    print(f"  [{'OK ' if good else '!! '}] {name}: {verb} (expected {want})")


def R(rat="a sufficiently long and meaningful rationale"):
    return rat


# --- still rejected (legitimate geometry constraints) ---
print("Legitimate rejections:")
expect("non-sequential sequence_id", [
    {"sequence_id": 1, "primitive_type": "box", "parameters": {"length": 10, "width": 10, "height": 5}, "operation": "new", "rationale": R()},
    {"sequence_id": 3, "primitive_type": "cylinder", "parameters": {"radius": 3, "height": 5}, "operation": "cut", "rationale": R()},
], should_pass=False)
expect("rationale too short", [
    {"sequence_id": 1, "primitive_type": "box", "parameters": {"length": 10, "width": 10, "height": 5}, "operation": "new", "rationale": "too short"},
], should_pass=False)
expect("invented primitive_type (rounded_box)", [
    {"sequence_id": 1, "primitive_type": "rounded_box", "parameters": {"width": 5, "length": 5, "height": 5, "radius": 1}, "operation": "new", "rationale": R()},
], should_pass=False)
expect("extra param not in schema", [
    {"sequence_id": 1, "primitive_type": "box", "parameters": {"length": 10, "width": 10, "height": 5, "radius": 2}, "operation": "new", "rationale": R()},
], should_pass=False)
expect("hollow_box wall too thick", [
    {"sequence_id": 1, "primitive_type": "hollow_box", "parameters": {"length": 10, "width": 10, "height": 10, "wall_thickness": 6.0}, "operation": "new", "rationale": R()},
], should_pass=False)
expect("hollow_cylinder inner >= outer", [
    {"sequence_id": 1, "primitive_type": "hollow_cylinder", "parameters": {"outer_radius": 5, "inner_radius": 6, "height": 10}, "operation": "new", "rationale": R()},
], should_pass=False)
expect("invented CadQuery op in custom", [
    {"sequence_id": 1, "primitive_type": "custom", "operation": "new", "rationale": R(),
     "parameters": {"shape_description": "x", "cadquery_operations": ["NotACadQueryClass.doStuff"], "code_sketch": "result = cq.Workplane('XY').box(1,1,1)", "declared_dimensions": {}}},
], should_pass=False)
expect("real CadQuery op not in curated KB (Edge.fillet) accepted", [
    {"sequence_id": 1, "primitive_type": "custom", "operation": "new", "rationale": R(),
     "parameters": {"shape_description": "x", "cadquery_operations": ["Workplane.rect", "Workplane.extrude", "Edge.fillet"], "code_sketch": "result = cq.Workplane('XY').box(1,1,1)", "declared_dimensions": {}}},
], should_pass=True)

# --- now correctly accepted (previously bandaged into rejection) ---
print("Correctly accepted (bandages removed):")
expect("10 cylinders (5 legs + 5 wheels)", [
    {"sequence_id": i + 1, "primitive_type": "cylinder", "parameters": {"radius": 3, "height": 5}, "operation": "join" if i else "new", "rotation": [0, 0, i * 36], "rationale": R("a repeated structural cylinder member")}
    for i in range(10)], should_pass=True)
expect("duplicate rationales across steps", [
    {"sequence_id": 1, "primitive_type": "box", "parameters": {"length": 10, "width": 10, "height": 5}, "operation": "new", "rationale": "identical justification shared by symmetric parts"},
    {"sequence_id": 2, "primitive_type": "box", "parameters": {"length": 10, "width": 10, "height": 5}, "operation": "join", "position": [20, 0, 0], "rationale": "identical justification shared by symmetric parts"},
], should_pass=True)
expect("large part vs overall dims", [
    {"sequence_id": 1, "primitive_type": "box", "parameters": {"length": 100, "width": 10, "height": 10}, "operation": "new", "rationale": R()},
], should_pass=True)
expect("assumptions present, clarifications empty", [
    {"sequence_id": 1, "primitive_type": "box", "parameters": {"length": 10, "width": 10, "height": 5}, "operation": "new", "rationale": R()},
], should_pass=True, override={"assumptions": ["a default"], "clarifications": []})
expect("empty assumptions and clarifications", [
    {"sequence_id": 1, "primitive_type": "box", "parameters": {"length": 10, "width": 10, "height": 5}, "operation": "new", "rationale": R()},
], should_pass=True, override={"assumptions": [], "clarifications": []})

print(f"\n{ok}/{total} boundary checks behaved as expected", "\u2713" if ok == total else "\u2717")
sys.exit(0 if ok == total else 1)
