"""
test_mates_and_assembly.py — relational placement (mates) + assembly support.

Proves the planning-level fix for connectivity: parts attach to each other and the
kernel DERIVES positions so they touch by construction (no guessed coordinates),
and multi-part assemblies are verified against the declared part count.

Run:  python tests/test_mates_and_assembly.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))

import kernel
import verify
from schemas.geometry_plan import GeometryPlan

ok = 0
total = 0


def check(label, cond):
    global ok, total
    total += 1
    ok += bool(cond)
    print(f"  [{'OK ' if cond else '!! '}] {label}")


def plan(seq, kind="single_solid"):
    return {"title": "t", "assembly_kind": kind,
            "overall_dimensions": {"width": 600, "length": 600, "height": 800},
            "engineering_requirements": {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []},
            "assumptions": ["x"], "clarifications": [], "primitives_sequence": seq}


def comps(p):
    r = kernel.build_plan(p)
    if not r["ok"]:
        return None, r
    return verify.measure(verify.cq_to_meshlib(r["solid"]))["components"], r


# 1. mates connect parts by construction
p1 = plan([
    {"sequence_id": 1, "name": "base", "primitive_type": "box", "parameters": {"length": 40, "width": 40, "height": 20}, "operation": "new", "rationale": "base block of the stack"},
    {"sequence_id": 2, "name": "mid", "primitive_type": "box", "parameters": {"length": 30, "width": 30, "height": 20}, "operation": "join", "attach": {"to": "base", "at": "top"}, "rationale": "mid mated to base top"},
    {"sequence_id": 3, "name": "top", "primitive_type": "box", "parameters": {"length": 20, "width": 20, "height": 20}, "operation": "join", "attach": {"to": "mid", "at": "top"}, "rationale": "top mated to mid top"},
])
GeometryPlan(**p1)
c1, _ = comps(p1)
check("3 mated boxes form ONE connected solid", c1 == 1)

# 2. gap is respected
p2 = plan([
    {"sequence_id": 1, "name": "base", "primitive_type": "box", "parameters": {"length": 40, "width": 40, "height": 20}, "operation": "new", "rationale": "base block"},
    {"sequence_id": 2, "name": "f", "primitive_type": "box", "parameters": {"length": 20, "width": 20, "height": 20}, "operation": "join", "attach": {"to": "base", "at": "top", "gap": 5.0}, "rationale": "block 5mm above base"},
])
c2, _ = comps(p2)
check("a 5mm mate gap leaves parts disconnected (2 components)", c2 == 2)

# 3. assembly counts parts
p3 = plan([
    {"sequence_id": 1, "name": "bracket", "part": "bracket", "primitive_type": "box", "parameters": {"length": 40, "width": 40, "height": 10}, "operation": "new", "rationale": "the bracket body"},
    {"sequence_id": 2, "name": "bolt", "part": "bolt", "primitive_type": "cylinder", "parameters": {"radius": 4, "height": 30}, "operation": "new", "position": [0, 0, 25], "rationale": "a separate bolt part"},
], kind="assembly")
GeometryPlan(**p3)
r3 = kernel.build_plan(p3)
v3 = verify.verify_solid(r3["solid"], expected_components=r3["meta"]["part_count"])
check("assembly declares 2 parts and verifies as 2 components", r3["meta"]["part_count"] == 2 and v3["verdict"] == "PASS")

# 4. cycle detection
p4 = plan([
    {"sequence_id": 1, "name": "A", "primitive_type": "box", "parameters": {"length": 10, "width": 10, "height": 10}, "operation": "new", "attach": {"to": "B", "at": "top"}, "rationale": "A attaches to B (cycle)"},
    {"sequence_id": 2, "name": "B", "primitive_type": "box", "parameters": {"length": 10, "width": 10, "height": 10}, "operation": "join", "attach": {"to": "A", "at": "top"}, "rationale": "B attaches to A (cycle)"},
])
r4 = kernel.build_plan(p4)
check("attach cycle is caught (no hang/crash)", (not r4["ok"]) and "cycle" in (r4.get("error", "")))

# 5. a full mated chair is ONE connected solid (the headline fix)
steps = [{"sequence_id": 1, "name": "hub", "primitive_type": "cylinder", "parameters": {"radius": 35, "height": 40}, "operation": "new", "position": [0, 0, 20], "rationale": "central hub of the star base"}]
sid = 2
for i in range(5):
    steps.append({"sequence_id": sid, "name": f"leg{i}", "primitive_type": "box", "parameters": {"length": 300, "width": 40, "height": 30}, "operation": "join", "position": [130, 0, 15], "rotation": [0, 0, i * 72], "rationale": "radial leg overlapping the hub"})
    sid += 1
steps += [
    {"sequence_id": sid, "name": "column", "primitive_type": "cylinder", "parameters": {"radius": 25, "height": 300}, "operation": "join", "attach": {"to": "hub", "at": "top"}, "rationale": "column mated to hub top"},
    {"sequence_id": sid + 1, "name": "seat", "primitive_type": "filleted_box", "parameters": {"length": 450, "width": 450, "height": 50, "fillet_val": 15}, "operation": "join", "attach": {"to": "column", "at": "top"}, "rationale": "seat mated to column top"},
    {"sequence_id": sid + 2, "name": "backrest", "primitive_type": "filleted_box", "parameters": {"length": 450, "width": 50, "height": 400, "fillet_val": 12}, "operation": "join", "attach": {"to": "seat", "at": "back", "my_anchor": "bottom"}, "rationale": "backrest mated to seat back edge"},
]
pc = plan(steps)
GeometryPlan(**pc)
c5, _ = comps(pc)
check("a full chair built with mates is ONE connected solid (was 8)", c5 == 1)

print(f"\n{ok}/{total} mate/assembly checks passed", "\u2713" if ok == total else "\u2717")
sys.exit(0 if ok == total else 1)
