"""
Phase 9 — the single_solid MONOLITHIC-FUSION path (the impeller class).

The chair is an `assembly` (parts kept separate, combined by `.add()` + contact — NO boolean
fuse), so it never exercised the single_solid boolean-fuse path. The impeller run
(`logs/geometry_planning_2026-06-27T12-34-17-371Z.jsonl`) exposed a SILENT correctness bug there:

  step 34: revolved hub + bore (cut)            -> PASS, ~166,000 mm^3, hub visible.
  step 45: hub + bore + a CLEAN blade (join)    -> PASS but volume == 1,658 mm^3 == the blade ONLY;
                                                   the hub (the LARGEST body) was silently dropped
                                                   by the union, and verify rubber-stamped it PASS.

The defect: `kernel._combined_ok(out, "union")` only checked `volume > 1e-9`, so a union whose
result shrank BELOW its largest operand (impossible for a real union -> a body was dropped) was
accepted. A union can NEVER be smaller than either operand.

These tests assert the INVARIANT: fusing a body onto a single_solid keeps BOTH bodies — the result
volume is >= the largest contributing body (minus what cuts legitimately remove), and the object is
ONE connected component. They reproduce the bug on the unfixed kernel and lock the fix.
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


def _plan(seq, kind="single_solid", w=100, l=100, h=50):
    return {"title": "impeller-fusion", "assembly_kind": kind,
            "overall_dimensions": {"width": w, "length": l, "height": h},
            "engineering_requirements": _reqs(), "assumptions": [], "clarifications": [],
            "primitives_sequence": seq, "contains_freeform": True}


# The exact hub the run used: a turned cone-ish backplate, Ø100 at base tapering to Ø30, 50mm tall.
HUB = {"sequence_id": 1, "name": "hub", "primitive_type": "revolved_profile",
       "parameters": {"profile": [[50, 0], [48, 5], [42, 15], [32, 30], [20, 45], [15, 50]],
                      "end_fillet": 0.0},
       "operation": "new", "rationale": "central hub / backplate"}

BORE = {"sequence_id": 2, "name": "bore", "primitive_type": "cylinder",
        "parameters": {"radius": 10, "height": 60}, "operation": "cut",
        "position": [0, 0, 25], "rationale": "central shaft bore"}


def _custom_blade(sid=3, op="join"):
    # The run's blade: a twisted loft of rotated rectangles (a single, clean blade).
    code = (
        "import cadquery as cq\n"
        "result = cq.Workplane(\"XY\")\n"
        "heights = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]\n"
        "radii   = [50.0, 45.0, 38.0, 32.0, 24.0, 15.0]\n"
        "angles  = [0.0, 4.0, 8.0, 12.0, 16.0, 20.0]\n"
        "thickness = 1.5\n"
        "for i in range(len(heights)):\n"
        "    z = heights[i]; r = radii[i]; angle = angles[i]\n"
        "    length = r - 12.0; cx = 12.0 + length / 2.0\n"
        "    if i == 0:\n"
        "        result = result.workplane(offset=z).transformed(rotate=(0,0,angle)).moveTo(cx,0).rect(length, thickness)\n"
        "    else:\n"
        "        dz = z - heights[i-1]\n"
        "        result = result.workplane(offset=dz).transformed(rotate=(0,0,angle-angles[i-1])).moveTo(cx,0).rect(length, thickness)\n"
        "result = result.loft(combine=True)\n"
    )
    return {"sequence_id": sid, "name": "blade", "primitive_type": "custom",
            "parameters": {"shape_description": "a single twisted blade",
                           "cadquery_operations": ["Workplane.loft", "Workplane.rect", "Workplane.transformed"],
                           "code_sketch": code, "declared_dimensions": {}},
            "operation": op, "rationale": "one blade fused to the hub"}


def _hub_minus_bore_volume():
    """Build hub+bore alone and measure — the floor the full fused solid must not fall below."""
    res = kernel.build_plan(_plan([HUB, BORE]))
    assert res["ok"], res
    return res["solid"].val().Volume()


def test_single_solid_join_keeps_the_hub():
    """hub + bore + 1 custom blade (join) must KEEP the hub: result volume ~>= (hub-bore) volume,
    and be ONE connected component. On the unfixed kernel the hub is silently dropped -> FAIL."""
    floor = _hub_minus_bore_volume()
    res = kernel.build_plan(_plan([HUB, BORE, _custom_blade()]))
    assert res["ok"], f"build should not error: {res.get('error')}"
    vol = res["solid"].val().Volume()
    print(f"hub-minus-bore volume = {floor:.1f} mm^3 ; fused (hub+bore+blade) volume = {vol:.1f} mm^3")
    # A union with the blade can only ADD volume to the hub; it can never shrink below the hub.
    assert vol >= floor * 0.98, (
        f"BODY SILENTLY DROPPED: fused volume {vol:.1f} < hub-minus-bore {floor:.1f}. "
        f"The join discarded the hub (the largest body).")
    rep = verify_mod.verify_solid(res["solid"], plan=_plan([HUB, BORE, _custom_blade()]))
    comp = next((c for c in rep["checks"] if c["name"] == "component_count"), None)
    assert comp and comp["passed"], f"must be ONE connected component: {comp}"
    print("PASS single_solid join keeps the hub (no silent body-drop), one component")


def test_fused_single_solid_passes_the_backstop():
    """On the FIXED kernel, the hub is kept, so the new no_dropped_body invariant is present and
    PASSES (the gate is consistent with a sound fused body)."""
    plan = _plan([HUB, BORE, _custom_blade()])
    res = kernel.build_plan(plan)
    assert res["ok"], res.get("error")
    fa = res["meta"].get("fusion_audit")
    assert fa and fa.get("applicable"), f"single_solid should carry an applicable fusion_audit: {fa}"
    rep = verify_mod.verify_solid(res["solid"], plan=plan, fusion_audit=fa)
    ndb = next((c for c in rep["checks"] if c["name"] == "no_dropped_body"), None)
    assert ndb is not None, "the no_dropped_body invariant must be evaluated for this single_solid"
    assert ndb["passed"], f"a sound fused body must pass no_dropped_body: {ndb['detail']}"
    assert rep["verdict"] == "PASS", rep.get("localized_fix")
    print("PASS fused single_solid satisfies the no_dropped_body backstop")


def test_verify_backstop_FAILS_a_dropped_body():
    """Gate test (independent of the kernel): give verify a SMALL solid (the blade only) but a
    fusion_audit that says a large hub body should be present -> the backstop must FAIL it LOUDLY,
    not silently PASS. This is the invariant that would have caught the impeller bug at the gate."""
    # Build just the blade (a small body) on its own.
    blade_only = _plan([dict(_custom_blade(sid=1, op="new"))])
    res = kernel.build_plan(blade_only)
    assert res["ok"], res.get("error")
    blade_vol = res["solid"].val().Volume()
    # Pretend the plan also built a big hub that should have survived a join.
    audit = {"applicable": True, "max_additive_volume": blade_vol * 40.0,
             "total_cut_volume": 0.0, "largest_additive_name": "hub"}
    rep = verify_mod.verify_solid(res["solid"], plan=blade_only, fusion_audit=audit)
    ndb = next((c for c in rep["checks"] if c["name"] == "no_dropped_body"), None)
    assert ndb is not None and not ndb["passed"], f"backstop must FAIL a dropped body: {ndb}"
    assert rep["verdict"] == "FAIL", "verdict must be FAIL when a body was dropped"
    assert "DROPPED" in ndb["detail"], ndb["detail"]
    print("PASS verify backstop FAILs a single_solid that dropped a body (loud, actionable)")


def _twisted_blade_sections(r_in=12.0, r_out=46.0, thick=3.0, height=50.0,
                            n=6, twist_deg=22.0):
    """A clean twisted radial fin as lofted_sections rows [z, x1,y1, ...]: a thin radial rectangle
    (r_in..r_out, tangential thickness `thick`) rotated progressively to `twist_deg` over `height`."""
    import math
    rows = []
    for k in range(n):
        z = height * k / (n - 1)
        theta = math.radians(twist_deg * (z / height))
        corners = [(r_in, -thick / 2), (r_out, -thick / 2), (r_out, thick / 2), (r_in, thick / 2)]
        row = [round(z, 4)]
        for (x, y) in corners:
            rx = x * math.cos(theta) - y * math.sin(theta)
            ry = x * math.sin(theta) + y * math.cos(theta)
            row += [round(rx, 4), round(ry, 4)]
        rows.append(row)
    return rows


def test_patterned_blades_fuse_into_one_body():
    """The GENERAL monolithic path: hub + bore-cut + ONE lofted_sections blade with a RADIAL
    pattern (count 7) fused via `join`. The kernel must rotate + FUSE all 7 copies onto the hub so
    the result is exactly ONE connected, sound body (not 7 floating blades, not a hub-less blob)."""
    blade = {"sequence_id": 3, "name": "blade", "primitive_type": "lofted_sections",
             "parameters": {"sections": _twisted_blade_sections()},
             "operation": "join",
             "pattern": {"kind": "radial", "count": 7, "axis": "z"},
             "rationale": "one blade, patterned 7x around the hub and fused"}
    plan = _plan([HUB, BORE, blade])
    res = kernel.build_plan(plan)
    assert res["ok"], f"patterned-fusion build should not error: {res.get('error')}"
    floor = _hub_minus_bore_volume()
    vol = res["solid"].val().Volume()
    print(f"hub-minus-bore = {floor:.1f} mm^3 ; hub + 7 fused blades = {vol:.1f} mm^3")
    assert vol >= floor * 0.98, f"the hub must survive the patterned fusion: {vol:.1f} < {floor:.1f}"
    rep = verify_mod.verify_solid(res["solid"], plan=plan, fusion_audit=res["meta"].get("fusion_audit"))
    comp = next(c for c in rep["checks"] if c["name"] == "component_count")
    assert comp["passed"], f"7 patterned blades + hub must be ONE component: {comp['detail']}"
    assert rep["verdict"] == "PASS", f"patterned impeller body must verify PASS: {rep.get('localized_fix')}"
    print("PASS radial pattern of a contour blade FUSES into ONE sound body (7 blades on a hub)")


def test_twisted_loft_primitive_builds_sound():
    """Task 5: the GENERAL twisted_loft technique builds a clean twisted blade from NUMBERS ALONE
    (no custom code). One sound solid; the kernel owns the geometry."""
    blade = {"sequence_id": 1, "name": "blade", "primitive_type": "twisted_loft",
             "parameters": {
                 "profile": [[-17.0, -1.5], [17.0, -1.5], [17.0, 1.5], [-17.0, 1.5]],
                 "stations": [[0.0, 29.0, 0.0, 1.0], [12.5, 29.0, 6.0, 1.0],
                              [25.0, 29.0, 12.0, 1.0], [37.5, 29.0, 18.0, 0.9],
                              [50.0, 29.0, 24.0, 0.8]]},
             "operation": "new", "rationale": "a single host-built twisted vane"}
    plan = _plan([blade])
    res = kernel.build_plan(plan)
    assert res["ok"], f"twisted_loft must build: {res.get('error')}"
    rep = verify_mod.verify_solid(res["solid"], plan=plan,
                                  fusion_audit=res["meta"].get("fusion_audit"))
    checks = {c["name"]: c for c in rep["checks"]}
    assert checks["watertight"]["passed"], checks["watertight"]["detail"]
    assert checks["no_self_intersections"]["passed"], checks["no_self_intersections"]["detail"]
    assert checks["component_count"]["passed"], checks["component_count"]["detail"]
    print(f"PASS twisted_loft builds a sound vane from numbers (vol {res['solid'].val().Volume():.0f} mm^3)")


if __name__ == "__main__":
    test_single_solid_join_keeps_the_hub()
    test_fused_single_solid_passes_the_backstop()
    test_verify_backstop_FAILS_a_dropped_body()
    test_patterned_blades_fuse_into_one_body()
    test_twisted_loft_primitive_builds_sound()
    print("\nALL single_solid fusion tests passed.")
