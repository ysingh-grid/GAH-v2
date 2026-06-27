"""
Fix C / C1+C2 (deterministic): robust boolean-combine + assembly-by-contact.

The agent's curved-chair builds crashed with `modifier/combine error: ValueError: Null TopoDS_Shape
object` whenever a swept_circle was boolean-`join`ed with another solid. These tests assert:
  (a) that fuse now NEVER leaks a raw OCC null — it either builds OR fails with a clean, structured
      GeometryCombineError carrying a design-level FIX directive;
  (b) a normal box+box union still builds (no regression);
  (c) the SAME base modeled the RECOMMENDED way — an ASSEMBLY of touching parts (operation 'new' +
      attach + rotation, no fuse) — builds and verifies COHERENT (this is the path the kernel snaps).
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


def _plan(seq, kind="single_solid", w=650, l=650, h=60):
    return {"title": "t", "assembly_kind": kind,
            "overall_dimensions": {"width": w, "length": l, "height": h},
            "engineering_requirements": _reqs(), "assumptions": [], "clarifications": [],
            "primitives_sequence": seq}


def test_swept_join_no_raw_null():
    # The exact failing shape: revolved hub + swept_circle arm, fused (operation join), single_solid.
    plan = _plan([
        {"sequence_id": 1, "name": "hub", "primitive_type": "revolved_profile",
         "parameters": {"profile": [[50, 0], [50, 10], [40, 60], [30, 60]], "end_fillet": 0.0},
         "operation": "new", "rationale": "central hub of the five-star base"},
        {"sequence_id": 2, "name": "arm", "primitive_type": "swept_circle",
         "parameters": {"radius": 15.0, "path": [[40, 0, 40], [150, 0, 35], [280, 0, 15], [325, 0, 10]]},
         "operation": "join", "rationale": "one swept arm fused to the hub"},
    ])
    res = kernel.build_plan(plan)
    if res["ok"]:
        print("PASS swept_circle+join now builds a valid solid (robust fuse recovered it)")
    else:
        err = res.get("error") or ""
        assert "could not join" in err and "FIX (design-level" in err, \
            f"a fuse failure must be a structured GeometryCombineError, got: {err!r}"
        assert "modifier/combine error: ValueError: Null TopoDS_Shape object" not in err or "FIX" in err, err
        print("PASS swept_circle+join fails CLEANLY with a design-level GeometryCombineError (no raw null)")


def test_box_union_still_works():
    plan = _plan([
        {"sequence_id": 1, "name": "a", "primitive_type": "box",
         "parameters": {"length": 40, "width": 40, "height": 40}, "operation": "new",
         "rationale": "first box of the union regression test"},
        {"sequence_id": 2, "name": "b", "primitive_type": "box",
         "parameters": {"length": 40, "width": 40, "height": 40}, "operation": "join",
         "position": [20, 0, 0], "rationale": "overlapping box joined to the first"},
    ], w=60, l=40, h=40)
    res = kernel.build_plan(plan)
    assert res["ok"], res
    assert res["solid"].val().Volume() > 0, "union must produce a positive-volume solid"
    print("PASS normal box+box union still builds (no regression)")


def test_assembly_by_contact_base_is_coherent():
    # The RECOMMENDED path: each arm is its OWN part (operation 'new'), attached to the hub with
    # rotation — no boolean fuse. The kernel snaps them into contact -> one coherent object.
    seq = [{"sequence_id": 1, "name": "hub", "part": "base", "primitive_type": "cylinder",
            "parameters": {"radius": 60, "height": 60}, "operation": "new",
            "rationale": "central hub the arms attach to"}]
    for i in range(3):
        seq.append({"sequence_id": 2 + i, "name": f"arm_{i+1}", "part": f"arm_{i+1}",
                    "primitive_type": "box", "parameters": {"length": 300, "width": 40, "height": 20},
                    "operation": "new",
                    "attach": {"to": 1, "at": "bottom", "my_anchor": "top", "offset": [150, 0, 0]},
                    "rotation": [0, 0, i * 120.0],
                    "rationale": f"arm {i+1} attached to the hub (assembly-by-contact, no fuse)"})
    plan = _plan(seq, kind="assembly", w=700, l=700, h=120)
    res = kernel.build_plan(plan)
    assert res["ok"], res
    rep = verify_mod.verify_solid(res["solid"], plan=plan, part_solids=res["meta"]["part_solids"])
    assert rep["verdict"] == "PASS", f"assembly-by-contact base must be coherent: {rep.get('localized_fix')}"
    assert rep["coherence"]["num_clusters"] == 1, rep["coherence"]
    print("PASS assembly-by-contact base (no fuse) builds ONE coherent object")


if __name__ == "__main__":
    test_swept_join_no_raw_null()
    test_box_union_still_works()
    test_assembly_by_contact_base_is_coherent()
    print("\nALL robust-combine / assembly-by-contact tests passed.")
