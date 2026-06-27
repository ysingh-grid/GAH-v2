"""
Task 7 (deterministic): coherent + self-checking placement.

Before, an `attach.offset` was applied in the GLOBAL frame, so five radial legs (each rotated by
k*72 deg, offset [R,0,0]) all shoved +R in global X — they clumped and didn't touch the hub, and
NO arrangement of per-instance attach could build a 5-star base (the failing run looped on this).
Now the offset is expressed in the part's ROTATED frame, so it rotates WITH the part and the star
forms + touches the hub. Also: the contact check (verify_assembly_coherence) runs BEFORE any
render/vision and reports the exact gap, giving instant deterministic feedback.
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


def _five_star_base():
    seq = [{"sequence_id": 1, "name": "hub", "part": "base", "primitive_type": "cylinder",
            "parameters": {"radius": 60, "height": 60}, "operation": "new",
            "rationale": "the central hub all five legs radiate from"}]
    sid = 2
    for i in range(5):
        ang = i * 72.0
        leg_id = sid
        seq.append({"sequence_id": leg_id, "name": f"leg_{i+1}", "part": f"leg_{i+1}",
                    "primitive_type": "box",
                    "parameters": {"length": 300, "width": 40, "height": 20}, "operation": "new",
                    "attach": {"to": 1, "at": "bottom", "my_anchor": "top", "offset": [150, 0, 0]},
                    "rotation": [0, 0, ang],
                    "rationale": f"radial leg {i+1} of the five-star base, rotated and slid outward"})
        seq.append({"sequence_id": leg_id + 1, "name": f"caster_{i+1}", "part": f"caster_{i+1}",
                    "primitive_type": "cylinder",
                    "parameters": {"radius": 25, "height": 30}, "operation": "new",
                    "attach": {"to": leg_id, "at": "bottom", "my_anchor": "top", "offset": [140, 0, 0]},
                    "rotation": [0, 0, ang],
                    "rationale": f"caster {i+1} at the outer end of leg {i+1}"})
        sid += 2
    return {"title": "five star base", "assembly_kind": "assembly",
            "overall_dimensions": {"width": 600, "length": 600, "height": 120},
            "engineering_requirements": _reqs(), "assumptions": [], "clarifications": [],
            "primitives_sequence": seq}


def test_radial_base_is_one_coherent_object():
    plan = _five_star_base()
    res = kernel.build_plan(plan)
    assert res["ok"], res
    rep = verify_mod.verify_solid(res["solid"], plan=plan, part_solids=res["meta"].get("part_solids"))
    coh = rep.get("coherence", {})
    assert rep["verdict"] == "PASS", f"5-star base must be ONE coherent object now: {rep.get('localized_fix')}"
    assert coh.get("contact_connected") and coh.get("num_clusters") == 1, coh
    assert coh.get("part_count") == 11, coh  # hub + 5 legs + 5 casters
    print("PASS 5-leg + 5-caster radial base builds as ONE coherent object (offset rotates with part)")


def test_bad_placement_gives_instant_gap_message():
    # Two parts placed far apart (no valid mate) -> coherence FAILS with a precise, instant gap
    # message, BEFORE any render/vision step.
    plan = {"title": "gapped", "assembly_kind": "assembly",
            "overall_dimensions": {"width": 100, "length": 100, "height": 100},
            "engineering_requirements": _reqs(), "assumptions": [], "clarifications": [],
            "primitives_sequence": [
                {"sequence_id": 1, "name": "a", "part": "a", "primitive_type": "box",
                 "parameters": {"length": 20, "width": 20, "height": 20}, "operation": "new",
                 "position": [0, 0, 0], "rationale": "first part, anchored at the origin"},
                {"sequence_id": 2, "name": "b", "part": "b", "primitive_type": "box",
                 "parameters": {"length": 20, "width": 20, "height": 20}, "operation": "new",
                 "position": [500, 0, 0], "rationale": "second part placed far away to force a gap"}]}
    res = kernel.build_plan(plan)
    assert res["ok"], res
    rep = verify_mod.verify_solid(res["solid"], plan=plan, part_solids=res["meta"].get("part_solids"))
    assert rep["verdict"] == "FAIL", rep
    cae = next((c for c in rep["checks"] if c["name"] == "assembly_coherent"), None)
    assert cae and not cae["passed"], rep["checks"]
    iso = rep.get("coherence", {}).get("isolated_parts", [])
    assert iso and iso[0].get("gap_mm"), f"must report the precise gap, got {iso}"
    print(f"PASS bad placement returns an instant precise gap message (gap={iso[0]['gap_mm']}mm)")


if __name__ == "__main__":
    test_radial_base_is_one_coherent_object()
    test_bad_placement_gives_instant_gap_message()
    print("\nALL coherent-placement tests passed.")
