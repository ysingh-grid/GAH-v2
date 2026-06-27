import json
import sys
from cad_kernel.kernel import build_plan

plan = {
    "title": "Test Fix",
    "assembly_kind": "single_solid",
    "overall_dimensions": {"width": 100, "length": 100, "height": 100},
    "engineering_requirements": {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []},
    "assumptions": [],
    "clarifications": [],
    "primitives_sequence": [
        {
            "sequence_id": 1,
            "name": "my_box",
            "primitive_type": "box",
            "parameters": {"width": 50, "length": 50, "height": 50},
            "operation": "new",
            "position": [0, 0, 0],
            "rationale": "Base box"
        },
        {
            "sequence_id": 2,
            "name": "custom_join",
            "primitive_type": "custom",
            "parameters": {
                "shape_description": "Joining",
                "cadquery_operations": [],
                "code_sketch": "result = cq.Workplane('XY').add(my_box).faces('>Z').workplane().circle(10).extrude(10)",
                "declared_dimensions": {}
            },
            "operation": "join",
            "attach": {"to": 1, "at": "center"},
            "rationale": "Test accessing my_box"
        }
    ]
}

res = build_plan(plan)
if not res.get("ok"):
    print("FAILED:", json.dumps(res, indent=2, default=str))
    sys.exit(1)
print("SUCCESS! Steps:", len(res["steps"]))
