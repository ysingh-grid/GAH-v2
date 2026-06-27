"""
Mating-quality gate (deterministic): the host verifies that assembled parts MATE FLUSH and do not
partially BURY into each other ("dug inside" — the office-chair backrest-into-seat artifact), while
still ALLOWING intended insertions (telescoping cylinders, peg-in-hole, an embedded reinforcing
spine). Classification uses the containment ratio c = V_intersection / min(volA, volB):
  c >= CONTAINMENT_RATIO -> intended insertion (allowed); below a small volume floor -> flush
  contact (allowed); in between -> a BAD partial interpenetration (flagged + the verdict FAILs).
"""
import os
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))
os.environ.setdefault("PRIMITIVES_JSON_DATA", (ROOT / "schemas" / "primitives.json").read_text())

import cadquery as cq               # noqa: E402
import kernel                       # noqa: E402
import verify as verify_mod         # noqa: E402


def _coh(parts):
    return verify_mod.verify_assembly_coherence(OrderedDict(parts))


# ---- classification (verify_assembly_coherence) ---------------------------------------

def test_partial_burial_is_flagged():
    # Two equal boxes overlapping 50% along X -> c = 0.5 (mid-range) -> BAD interpenetration.
    a = cq.Workplane("XY").box(40, 40, 40)
    b = cq.Workplane("XY").box(40, 40, 40).translate((20, 0, 0))
    coh = _coh([("a", a), ("b", b)])
    assert coh["interpenetrations"], f"50% overlap must be flagged: {coh}"
    assert not coh["insertions"], coh
    x = coh["interpenetrations"][0]
    assert 0.4 < x["overlap_fraction"] < 0.6, x
    print("PASS two boxes overlapping 50% -> flagged as interpenetration")


def test_telescoping_is_an_allowed_insertion():
    # Inner cylinder fully inside the outer (coaxial, shorter) -> c ~ 1 -> intended insertion.
    outer = cq.Workplane("XY").cylinder(40, 10)   # cylinder(height, radius): h40 r10, centered
    inner = cq.Workplane("XY").cylinder(30, 4)    # h30 r4, fully inside outer
    coh = _coh([("outer", outer), ("inner", inner)])
    assert not coh["interpenetrations"], f"telescoping must NOT be flagged: {coh}"
    assert coh["insertions"], coh
    print("PASS telescoping (inner inside outer) -> intended insertion, not flagged")


def test_peg_in_hole_is_an_allowed_insertion():
    # A thin post fully embedded in a block -> c ~ 1 -> intended insertion.
    block = cq.Workplane("XY").box(40, 40, 40)
    peg = cq.Workplane("XY").cylinder(40, 3)
    coh = _coh([("block", block), ("peg", peg)])
    assert not coh["interpenetrations"], f"embedded peg must NOT be flagged: {coh}"
    assert coh["insertions"], coh
    print("PASS peg fully seated in a block -> intended insertion")


def test_spine_in_cushion_is_an_allowed_insertion():
    # A thin reinforcing spine ~83% inside a cushion slab -> c >= 0.75 -> intended insertion.
    cushion = cq.Workplane("XY").box(40, 10, 50)
    spine = cq.Workplane("XY").box(4, 4, 60)
    coh = _coh([("cushion", cushion), ("spine", spine)])
    assert not coh["interpenetrations"], f"embedded spine must NOT be flagged: {coh}"
    assert coh["insertions"], coh
    print("PASS thin spine mostly inside a cushion -> intended insertion")


def test_flush_contact_is_neither():
    # Face-to-face boxes: ~0 intersection volume -> below the floor -> flush contact (allowed).
    a = cq.Workplane("XY").box(40, 40, 40)
    b = cq.Workplane("XY").box(40, 40, 40).translate((40, 0, 0))
    coh = _coh([("a", a), ("b", b)])
    assert not coh["interpenetrations"], coh
    assert not coh["insertions"], coh
    assert coh["contact_connected"], coh
    print("PASS flush face-to-face contact -> neither flagged nor an insertion")


# ---- the hard gate (verify_solid verdict) ---------------------------------------------

def _reqs():
    return {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []}


def _plan(parts):
    return {"title": "gate", "assembly_kind": "assembly",
            "overall_dimensions": {"width": 100, "length": 100, "height": 100},
            "engineering_requirements": _reqs(), "assumptions": [], "clarifications": [],
            "primitives_sequence": parts}


def _boxstep(sid, name, pos):
    return {"sequence_id": sid, "name": name, "part": name, "primitive_type": "box",
            "parameters": {"length": 40, "width": 40, "height": 40}, "operation": "new",
            "position": pos, "rationale": f"box {name} for the mating-gate verdict test"}


def test_verdict_fails_on_interpenetration():
    # Absolute-position boxes (no attach -> never snapped) overlapping 50% -> verdict FAIL, no token.
    plan = _plan([_boxstep(1, "a", [0, 0, 0]), _boxstep(2, "b", [20, 0, 0])])
    res = kernel.build_plan(plan)
    assert res["ok"], res
    rep = verify_mod.verify_solid(res["solid"], plan=plan, part_solids=res["meta"]["part_solids"])
    assert rep["verdict"] == "FAIL", rep
    assert any(c["name"] == "no_interpenetration" and not c["passed"] for c in rep["checks"]), rep["checks"]
    print("PASS interpenetrating assembly -> verdict FAIL on no_interpenetration")


def test_flush_assembly_passes():
    plan = _plan([_boxstep(1, "a", [0, 0, 0]), _boxstep(2, "b", [40, 0, 0])])
    res = kernel.build_plan(plan)
    assert res["ok"], res
    rep = verify_mod.verify_solid(res["solid"], plan=plan, part_solids=res["meta"]["part_solids"])
    assert rep["verdict"] == "PASS", rep.get("localized_fix")
    assert any(c["name"] == "no_interpenetration" and c["passed"] for c in rep["checks"]), rep["checks"]
    print("PASS flush two-box assembly -> verdict PASS (no interpenetration)")


def test_intersection_volume_fails_open():
    # A gate must never crash the verdict: a broken mesh bridge -> intersection volume 0 (no flag).
    orig = verify_mod.mm.boolean
    verify_mod.mm.boolean = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        a = cq.Workplane("XY").box(40, 40, 40)
        b = cq.Workplane("XY").box(40, 40, 40).translate((20, 0, 0))
        coh = _coh([("a", a), ("b", b)])
        assert coh["interpenetrations"] == [] and coh["insertions"] == [], coh
        print("PASS interpenetration measurement fails OPEN (boolean error -> no flag, no crash)")
    finally:
        verify_mod.mm.boolean = orig


if __name__ == "__main__":
    test_partial_burial_is_flagged()
    test_telescoping_is_an_allowed_insertion()
    test_peg_in_hole_is_an_allowed_insertion()
    test_spine_in_cushion_is_an_allowed_insertion()
    test_flush_contact_is_neither()
    test_verdict_fails_on_interpenetration()
    test_flush_assembly_passes()
    test_intersection_volume_fails_open()
    print("\nALL interpenetration / mating-gate tests passed.")
