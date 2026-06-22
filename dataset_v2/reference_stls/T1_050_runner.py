
import json
import sys
import os

# Redirect the user code's output
_autofab_output = {"success": False}

try:
    # Execute the generated CadQuery code
    _autofab_user_globals = {}
    exec(open("/Users/ysingh/PycharmProjects/Capstone-v0.1/CADSmith/data/dataset_v2/reference_stls/T1_050_script.py").read(), _autofab_user_globals)

    # Find the CadQuery result object - look for common variable names
    import cadquery as cq
    _autofab_result = None

    # Priority order for finding the result shape
    _autofab_candidate_names = ["result", "model", "part", "shape", "assembly",
                                 "drone", "chassis", "bracket", "plate", "body"]

    for name in _autofab_candidate_names:
        obj = _autofab_user_globals.get(name)
        if obj is not None and isinstance(obj, cq.Workplane):
            _autofab_result = obj
            break

    # Fallback: find the last Workplane assigned
    if _autofab_result is None:
        for name, obj in reversed(list(_autofab_user_globals.items())):
            if name.startswith("_"):
                continue
            if isinstance(obj, cq.Workplane):
                _autofab_result = obj
                break

    if _autofab_result is None:
        _autofab_output = {"success": False, "error": "No CadQuery Workplane object found in script output. Assign your final shape to a variable named 'result'.", "error_type": "NoResultError"}
    else:
        # Extract geometry info
        solid = _autofab_result.val()
        bb = _autofab_result.val().BoundingBox()

        _autofab_geometry = {
            "volume": solid.Volume(),
            "center_of_mass": solid.Center().toTuple(),
            "bounding_box": {
                "xmin": bb.xmin, "xmax": bb.xmax, "xlen": bb.xlen,
                "ymin": bb.ymin, "ymax": bb.ymax, "ylen": bb.ylen,
                "zmin": bb.zmin, "zmax": bb.zmax, "zlen": bb.zlen,
            },
            "is_valid": solid.isValid(),
            "num_faces": len(_autofab_result.faces().vals()),
            "num_edges": len(_autofab_result.edges().vals()),
            "num_vertices": len(_autofab_result.vertices().vals()),
        }

        # Export STEP and STL
        cq.exporters.export(_autofab_result, "/Users/ysingh/PycharmProjects/Capstone-v0.1/CADSmith/data/dataset_v2/reference_stls/T1_050.step")
        cq.exporters.export(_autofab_result, "/Users/ysingh/PycharmProjects/Capstone-v0.1/CADSmith/data/dataset_v2/reference_stls/T1_050.stl")

        _autofab_output = {
            "success": True,
            "geometry": _autofab_geometry,
        }

except Exception as e:
    import traceback
    _autofab_output = {
        "success": False,
        "error": traceback.format_exc(),
        "error_type": type(e).__name__,
    }

# Write result to stdout as JSON
print("__AUTOFAB_RESULT__")
print(json.dumps(_autofab_output))
