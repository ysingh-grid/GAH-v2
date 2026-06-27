"""
Fix A (deterministic): host-enforced attach contact guarantee (snap-to-contact).

A part that DECLARED `attach.to` a target but drifted off its mate (bad offset/anchor) is snapped
back into contact with that target, so a fully-attached design can't be left undeliverable by an
imperfect offset — the exact failure in the latest office-chair run. INTENT-ONLY + FAIL-OPEN: an
absolute-position part is never moved (its disconnection signal + all related tests are preserved).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))
os.environ.setdefault("PRIMITIVES_JSON_DATA", (ROOT / "schemas" / "primitives.json").read_text())

import cadquery as cq               # noqa: E402
import kernel                       # noqa: E402
import verify as verify_mod         # noqa: E402


def _reqs():
    return {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []}


def _asm(parts, w=120, l=120, h=120):
    return {"title": "asm", "assembly_kind": "assembly",
            "overall_dimensions": {"width": w, "length": l, "height": h},
            "engineering_requirements": _reqs(), "assumptions": [], "clarifications": [],
            "primitives_sequence": parts}


def _box(sid, name, part, **kw):
    s = {"sequence_id": sid, "name": name, "part": part, "primitive_type": "box",
         "parameters": {"length": 40, "width": 40, "height": 40},
         "operation": kw.pop("operation", "new"),
         "rationale": f"part {name} for the snap-to-contact test"}
    s.update(kw)
    return s


def test_attached_but_drifted_part_snaps():
    # b declares attach to a, but an in-plane offset of 200mm in Z slides it far off the mate ->
    # WITHOUT snap it floats (disconnected). The host must snap it back into contact with a.
    plan = _asm([
        _box(1, "a", "a", position=[0, 0, 0]),
        _box(2, "b", "b", attach={"to": "a", "at": "right", "offset": [0, 0, 200]}),
    ])
    res = kernel.build_plan(plan)
    assert res["ok"], res
    snapped = res["meta"].get("snapped") or []
    assert any(s["part"] == "b" for s in snapped), f"b should have been snapped to contact, got {snapped}"
    rep = verify_mod.verify_solid(res["solid"], plan=plan, part_solids=res["meta"]["part_solids"])
    assert rep["verdict"] == "PASS", f"snapped assembly must be coherent: {rep.get('localized_fix')}"
    assert rep["coherence"]["num_clusters"] == 1, rep["coherence"]
    print("PASS a drifted attached part is snapped back into contact -> coherent")


def test_absolute_position_not_snapped():
    # b is placed by ABSOLUTE position (no attach) far away -> must NOT be snapped; coherence FAILS
    # (the disconnection signal + the 'position is for free-floating bodies' feature are preserved).
    plan = _asm([
        _box(1, "a", "a", position=[0, 0, 0]),
        _box(2, "b", "b", position=[200, 0, 0]),
    ], w=240)
    res = kernel.build_plan(plan)
    assert res["ok"], res
    assert not (res["meta"].get("snapped") or []), "absolute-position parts must never be snapped"
    rep = verify_mod.verify_solid(res["solid"], plan=plan, part_solids=res["meta"]["part_solids"])
    assert rep["verdict"] == "FAIL", "a floating absolute-position part must still fail coherence"
    print("PASS absolute-position float is NOT snapped (signal preserved)")


def test_snap_fail_open(monkeypatch=None):
    # If meshing blows up, snap must return the map UNCHANGED with [] (never crash, never worse).
    a = cq.Workplane("XY").box(40, 40, 40)
    b = cq.Workplane("XY").box(40, 40, 40).translate((200, 0, 0))
    from collections import OrderedDict
    m = OrderedDict([("a", a), ("b", b)])
    orig = verify_mod.cq_to_meshlib
    verify_mod.cq_to_meshlib = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        out_map, info = verify_mod.snap_assembly_to_contact(m, {"b": "a"})
        assert out_map is m and info == [], (out_map, info)
        print("PASS snap fails open (meshing error -> unchanged map, no crash)")
    finally:
        verify_mod.cq_to_meshlib = orig


def test_drifted_radial_base_snaps_to_coherent():
    # 3 legs declare attach to the hub but with an overshooting offset that floats them well clear
    # of the hub. Intent-snap must pull each back to contact -> one coherent base.
    seq = [{"sequence_id": 1, "name": "hub", "part": "base", "primitive_type": "cylinder",
            "parameters": {"radius": 60, "height": 60}, "operation": "new",
            "rationale": "central hub the legs attach to"}]
    for i in range(3):
        seq.append({"sequence_id": 2 + i, "name": f"leg_{i+1}", "part": f"leg_{i+1}",
                    "primitive_type": "box", "parameters": {"length": 300, "width": 40, "height": 20},
                    "operation": "new",
                    "attach": {"to": 1, "at": "bottom", "my_anchor": "top", "offset": [500, 0, 0]},
                    "rotation": [0, 0, i * 120.0],
                    "rationale": f"leg {i+1} attached to hub but overshooting -> must be snapped back"})
    plan = {"title": "drifted base", "assembly_kind": "assembly",
            "overall_dimensions": {"width": 700, "length": 700, "height": 120},
            "engineering_requirements": _reqs(), "assumptions": [], "clarifications": [],
            "primitives_sequence": seq}
    res = kernel.build_plan(plan)
    assert res["ok"], res
    snapped = {s["part"] for s in (res["meta"].get("snapped") or [])}
    assert {"leg_1", "leg_2", "leg_3"} <= snapped, f"all 3 overshooting legs should snap, got {snapped}"
    rep = verify_mod.verify_solid(res["solid"], plan=plan, part_solids=res["meta"]["part_solids"])
    assert rep["verdict"] == "PASS", f"snapped radial base must be coherent: {rep.get('localized_fix')}"
    assert rep["coherence"]["num_clusters"] == 1, rep["coherence"]
    print("PASS drifted 3-leg radial base is snapped to ONE coherent object")


def test_snap_lands_flush_not_buried():
    # b declares attach to a but an in-plane offset drifts it off the mate. The FLUSH snap must pull
    # it back into CONTACT without burying it (the old center-to-center snap could overshoot into a).
    plan = _asm([
        _box(1, "a", "a", position=[0, 0, 0]),
        _box(2, "b", "b", attach={"to": "a", "at": "right", "my_anchor": "left", "offset": [0, 0, 90]}),
    ])
    res = kernel.build_plan(plan)
    assert res["ok"], res
    rep = verify_mod.verify_solid(res["solid"], plan=plan, part_solids=res["meta"]["part_solids"])
    assert rep["verdict"] == "PASS", f"flush snap must yield a coherent, non-buried assembly: {rep.get('localized_fix')}"
    assert rep["coherence"]["num_clusters"] == 1, rep["coherence"]
    assert not rep["coherence"]["interpenetrations"], \
        f"flush snap must NOT bury the part: {rep['coherence']['interpenetrations']}"
    print("PASS flush snap lands the part in contact WITHOUT burial (no interpenetration)")


if __name__ == "__main__":
    test_attached_but_drifted_part_snaps()
    test_absolute_position_not_snapped()
    test_snap_fail_open()
    test_drifted_radial_base_snaps_to_coherent()
    test_snap_lands_flush_not_buried()
    print("\nALL snap-to-contact tests passed.")
