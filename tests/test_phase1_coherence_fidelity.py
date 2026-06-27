"""
test_phase1_coherence_fidelity.py — proves Phase 1 makes the token attest ONE COHERENT
OBJECT THAT LOOKS LIKE THE REQUEST (no fused blob, no bag of parts, no dropped features),
end to end at the host layer (no live LLM, vision stubbed).

Remove-it test: without coherence, a floating-part "assembly" or a fused blob would pass;
without fidelity, a sound object that abandons requested features would pass. These tests
assert the gate now catches all of those.
"""

import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))

os.environ["PRIMITIVES_JSON_DATA"] = (ROOT / "schemas" / "primitives.json").read_text()
TEST_SECRET = "phase1_test_secret"
os.environ["FORGECAD_RUN_SECRET"] = TEST_SECRET

import kernel                       # noqa: E402
import verify as verify_mod         # noqa: E402
import geometry_server as gs        # noqa: E402
from attestation import TOKEN_FIELD, verify_token  # noqa: E402


def _assembly(parts, w=80, l=40, h=40):
    return {"title": "asm", "assembly_kind": "assembly",
            "overall_dimensions": {"width": w, "length": l, "height": h},
            "engineering_requirements": {"functional": [], "environmental_thermal": [],
                                         "structural": [], "manufacturing_cost": []},
            "assumptions": [], "clarifications": [], "primitives_sequence": parts}


def _box(sid, name, part, **kw):
    s = {"sequence_id": sid, "name": name, "part": part, "primitive_type": "box",
         "parameters": {"length": 40, "width": 40, "height": 40},
         "operation": kw.pop("operation", "new"),
         "rationale": f"part {name} for the coherence test"}
    s.update(kw)
    return s


def _coherent_plan():
    return _assembly([
        _box(1, "a", "a", position=[0, 0, 0]),
        _box(2, "b", "b", attach={"to": "a", "at": "right"}),
    ])


def _floating_plan():
    return _assembly([
        _box(1, "a", "a", position=[0, 0, 0]),
        _box(2, "b", "b", position=[200, 0, 0]),
    ], w=240)


def _single_solid_plan():
    return {"title": "ss", "assembly_kind": "single_solid",
            "overall_dimensions": {"width": 10, "length": 10, "height": 10},
            "engineering_requirements": {"functional": [], "environmental_thermal": [],
                                         "structural": [], "manufacturing_cost": []},
            "assumptions": [], "clarifications": [],
            "primitives_sequence": [{"sequence_id": 1, "name": "x", "primitive_type": "box",
                                     "parameters": {"length": 10, "width": 10, "height": 10},
                                     "operation": "new", "rationale": "a single fused box"}]}


def _check(report, name):
    return next((c for c in report["checks"] if c["name"] == name), None)


def test_coherent_assembly_passes_coherence():
    p = _coherent_plan()
    r = kernel.build_plan(p)
    rep = verify_mod.verify_solid(r["solid"], plan=p, part_solids=r["meta"]["part_solids"])
    c = _check(rep, "assembly_coherent")
    assert c and c["passed"], rep
    assert _check(rep, "parts_sound")["passed"]
    print("OK: coherent mated assembly passes the coherence check")


def test_floating_part_fails_named():
    p = _floating_plan()
    r = kernel.build_plan(p)
    rep = verify_mod.verify_solid(r["solid"], plan=p, part_solids=r["meta"]["part_solids"])
    c = _check(rep, "assembly_coherent")
    assert c and not c["passed"], rep
    assert "b" in c["detail"] and ("attach" in c["detail"] and "gap" in c["detail"]), c["detail"]
    print(f"OK: floating part fails coherence, named with prescriptive fix -> {c['detail'][:80]}")


def test_single_solid_unchanged():
    p = _single_solid_plan()
    r = kernel.build_plan(p)
    rep = verify_mod.verify_solid(r["solid"], declared_bbox=[10, 10, 10], expected_components=1,
                                  plan=p, part_solids=r["meta"].get("part_solids"))
    names = [c["name"] for c in rep["checks"]]
    # bbox is now an OUTPUT, not a gating check.
    assert names == ["positive_volume", "watertight", "component_count",
                     "no_self_intersections"], names
    assert "bbox_matches_declared" not in names
    assert rep["verdict"] == "PASS"
    assert rep.get("measured_bbox") == [10.0, 10.0, 10.0], rep.get("measured_bbox")
    print("OK: single_solid path gates on soundness only; measured_bbox reported (not gated)")


def test_bbox_is_output_not_gate():
    # A sound part whose DECLARED overall_dimensions are wildly wrong still PASSES geometry —
    # the overall extent is an emergent output, not a self-audit. (The old gate failed this.)
    p = _single_solid_plan()  # a 10x10x10 box
    r = kernel.build_plan(p)
    rep = verify_mod.verify_solid(r["solid"], declared_bbox=[999, 999, 999], expected_components=1,
                                  plan=p, part_solids=r["meta"].get("part_solids"))
    assert rep["verdict"] == "PASS", rep["localized_fix"]
    assert rep["measured_bbox"] == [10.0, 10.0, 10.0]
    assert "bbox_matches_declared" not in [c["name"] for c in rep["checks"]]
    print("OK: bbox is an output — a wrong declared size no longer fails the geometric verdict")


def test_fidelity_pass_mints_token():
    os.environ["FORGECAD_FIDELITY_STUB"] = json.dumps({"recognizable": True, "missing_major_features": []})
    try:
        p = _coherent_plan()
        out = gs.build_verify_render(p)
        assert out["verdict"] == "PASS", out
        assert TOKEN_FIELD in out and verify_token(TEST_SECRET, p, out[TOKEN_FIELD])
        assert out["fidelity"]["status"] == "pass"
        print("OK: coherent + faithful -> token minted")
    finally:
        os.environ.pop("FORGECAD_FIDELITY_STUB", None)


def test_fidelity_reject_is_advisory_still_tokens():
    # Task 2: fidelity is ADVISORY. A sound + coherent model with a fidelity REJECT now still PASSES,
    # still mints a token, and is tagged trust_tier='needs_review' (was: verdict FAIL, no token — the
    # bug that discarded a sound chair). The fidelity feedback is still surfaced for optional refinement.
    os.environ["FORGECAD_FIDELITY_STUB"] = json.dumps(
        {"recognizable": False, "missing_major_features": ["legs", "casters"]})
    try:
        p = _coherent_plan()
        out = gs.build_verify_render(p)
        assert out["verdict"] == "PASS", out          # geometry+coherence sound -> PASS regardless of fidelity
        assert TOKEN_FIELD in out and verify_token(TEST_SECRET, p, out[TOKEN_FIELD]), out
        assert out.get("trust_tier") == "needs_review", out
        assert "legs" in out["next_action"] and "casters" in out["next_action"]
        print("OK: fidelity reject is ADVISORY -> verdict PASS, token issued, trust_tier=needs_review")
    finally:
        os.environ.pop("FORGECAD_FIDELITY_STUB", None)


def test_fidelity_unavailable_fails_open():
    # No stub and no reachable key -> critique returns 'unavailable' -> fail-open (token minted).
    os.environ.pop("FORGECAD_FIDELITY_STUB", None)
    saved = os.environ.pop("RLM_MODEL_API_KEY", None)
    try:
        p = _coherent_plan()
        out = gs.build_verify_render(p)
        assert out["verdict"] == "PASS", out
        assert TOKEN_FIELD in out, "infra-unavailable fidelity must fail OPEN (mint token)"
        assert out["fidelity"]["status"] == "unavailable"
        assert "UNAVAILABLE" in out["next_action"]
        print("OK: fidelity unavailable -> fail-open token + logged note")
    finally:
        if saved is not None:
            os.environ["RLM_MODEL_API_KEY"] = saved


def test_blob_with_dropped_features_is_only_needs_review():
    # Task 2 reframes the anti-blob guarantee: a sound featureless block is now DELIVERABLE (token
    # issued, so a run never yields nothing) but it can NEVER be 'certified' — a fidelity reject pins
    # it at trust_tier='needs_review' and surfaces the dropped features. So a blob is never passed off
    # as a good result, but it is also never silently discarded.
    os.environ["FORGECAD_FIDELITY_STUB"] = json.dumps(
        {"recognizable": False, "missing_major_features": ["legs", "backrest", "casters"]})
    try:
        blob = {"title": "Chair", "assembly_kind": "single_solid",
                "overall_dimensions": {"width": 60, "length": 60, "height": 60},
                "engineering_requirements": {"functional": [], "environmental_thermal": [],
                                             "structural": [], "manufacturing_cost": []},
                "assumptions": [], "clarifications": [],
                "primitives_sequence": [{"sequence_id": 1, "name": "blk", "primitive_type": "box",
                                         "parameters": {"length": 60, "width": 60, "height": 60},
                                         "operation": "new", "rationale": "a featureless block"}]}
        out = gs.build_verify_render(blob)
        assert out["verdict"] == "PASS", out
        assert TOKEN_FIELD in out, "sound geometry is deliverable (token issued) under advisory fidelity"
        assert out.get("trust_tier") == "needs_review", "a fidelity-rejected blob must never be 'certified'"
        assert "legs" in out["next_action"], out["next_action"]
        print("OK: sound blob is needs_review (never certified) but still deliverable (anti-blob reframed)")
    finally:
        os.environ.pop("FORGECAD_FIDELITY_STUB", None)


def test_fused_chair_passes_geometry():
    # The EXACT failure from logs/...09-39-39: a single_solid fused chair that built as a flawless
    # 1-component watertight solid but was blocked ONLY by the old bbox self-audit. It must now
    # pass geometry, report measured_bbox, and (with fidelity stubbed pass) mint a token.
    chair = {"title": "Office Chair", "assembly_kind": "single_solid",
             "overall_dimensions": {"width": 500, "length": 500, "height": 985},  # rough estimate
             "engineering_requirements": {"functional": [], "environmental_thermal": [],
                                          "structural": [], "manufacturing_cost": []},
             "assumptions": [], "clarifications": [],
             "primitives_sequence": [
                 {"sequence_id": 1, "name": "central_hub", "primitive_type": "cylinder",
                  "parameters": {"radius": 50, "height": 50}, "operation": "new",
                  "position": [0, 0, 0], "rationale": "central hub at origin"},
                 {"sequence_id": 2, "name": "leg1", "primitive_type": "box",
                  "parameters": {"width": 500, "length": 40, "height": 20}, "operation": "join",
                  "attach": {"to": 1, "at": "center", "my_anchor": "center"}, "rationale": "leg cross-bar one"},
                 {"sequence_id": 3, "name": "leg2", "primitive_type": "box",
                  "parameters": {"width": 40, "length": 500, "height": 20}, "operation": "join",
                  "attach": {"to": 1, "at": "center", "my_anchor": "center"}, "rationale": "leg cross-bar two"},
                 {"sequence_id": 4, "name": "gas_lift", "primitive_type": "cylinder",
                  "parameters": {"radius": 25, "height": 300}, "operation": "join",
                  "attach": {"to": 1, "at": "top", "my_anchor": "bottom"}, "rationale": "gas lift column"},
                 {"sequence_id": 5, "name": "seat_cushion", "primitive_type": "box",
                  "parameters": {"width": 450, "length": 450, "height": 50}, "operation": "join",
                  "attach": {"to": 4, "at": "top", "my_anchor": "bottom"}, "rationale": "seat cushion on lift"},
                 {"sequence_id": 6, "name": "backrest", "primitive_type": "box",
                  "parameters": {"width": 400, "length": 50, "height": 600}, "operation": "join",
                  "attach": {"to": 5, "at": "back", "my_anchor": "front", "offset": [0, 0, 275]},
                  "rationale": "backrest joined to seat"},
             ],
             "contains_freeform": False}
    r = kernel.build_plan(chair)
    rep = verify_mod.verify_solid(r["solid"], plan=chair, part_solids=r["meta"].get("part_solids"))
    assert rep["verdict"] == "PASS", f"chair must pass geometry now: {rep['localized_fix']}"
    assert rep.get("measured_bbox") and rep["measured_bbox"] != [500, 500, 985]
    os.environ["FORGECAD_FIDELITY_STUB"] = json.dumps({"recognizable": True, "missing_major_features": []})
    try:
        out = gs.build_verify_render(chair)
        assert out["verdict"] == "PASS" and TOKEN_FIELD in out, out.get("next_action")
        assert out.get("measured_bbox")
        print(f"OK: the fused chair now passes geometry + mints a token (measured_bbox={out['measured_bbox']})")
    finally:
        os.environ.pop("FORGECAD_FIDELITY_STUB", None)


def test_offset_along_normal_preserves_contact():
    # offset along the mate NORMAL is projected out (cannot lift a part off the mate). An in-plane
    # offset still SLIDES the part, but Fix A now SNAPS a drifted attached part back into contact —
    # so `attach` is an unbreakable contact guarantee (was: a large in-plane offset left it floating).
    pn = _assembly([
        _box(1, "a", "a", position=[0, 0, 0]),
        _box(2, "b", "b", attach={"to": "a", "at": "top", "my_anchor": "bottom", "offset": [0, 0, 25]}),
    ])
    rn = kernel.build_plan(pn)
    repn = verify_mod.verify_solid(rn["solid"], plan=pn, part_solids=rn["meta"]["part_solids"])
    assert _check(repn, "assembly_coherent")["passed"], "normal-offset must be ignored -> still touching"
    assert not (rn["meta"].get("snapped") or []), "an already-touching part needs no snap"
    # large in-plane offset slides b off a's face -> pre-Fix-A this floated; now it is snapped back.
    pi = _assembly([
        _box(1, "a", "a", position=[0, 0, 0]),
        _box(2, "b", "b", attach={"to": "a", "at": "top", "my_anchor": "bottom", "offset": [100, 0, 0]}),
    ])
    ri = kernel.build_plan(pi)
    assert any(s["part"] == "b" for s in (ri["meta"].get("snapped") or [])), "drifted attached b must be snapped"
    repi = verify_mod.verify_solid(ri["solid"], plan=pi, part_solids=ri["meta"]["part_solids"])
    assert _check(repi, "assembly_coherent")["passed"], "attach now GUARANTEES contact (snap restores it)"
    print("OK: normal-offset ignored; an in-plane offset that drifts off is snapped back (attach guarantees contact)")


def test_cluster_relative_prescriptive_diagnostic():
    p = _floating_plan()  # a at origin, b 200mm away
    r = kernel.build_plan(p)
    rep = verify_mod.verify_solid(r["solid"], plan=p, part_solids=r["meta"]["part_solids"])
    coh = rep["coherence"]
    assert coh["main_body"] == ["a"], coh["main_body"]
    iso = coh["isolated_parts"][0]
    assert iso["part"] == "b" and iso["nearest_in_main_body"] == "a"
    assert iso["gap_mm"] and iso["gap_mm"] > 100
    assert "attach 'b' to 'a'" in iso["hint"], iso["hint"]
    print(f"OK: disconnection diagnostic is main-body-relative + prescriptive -> {iso['hint'][:70]}")


def test_eyes_in_loop_visual_inspection():
    p = _floating_plan()
    os.environ["FORGECAD_SPATIAL_STUB"] = "Part 'b' floats ~160mm to the right, not touching the base."
    try:
        out = gs.build_verify_render(p)
        assert out["verdict"] == "FAIL"
        assert out.get("visual_inspection") == os.environ["FORGECAD_SPATIAL_STUB"]
        assert "VISUAL INSPECTION" in out["next_action"]
        print("OK: connectivity FAIL attaches a VISUAL INSPECTION (eyes in the loop)")
    finally:
        os.environ.pop("FORGECAD_SPATIAL_STUB", None)
    # fail-open: no stub, no key -> no crash, no visual note, verdict still FAIL
    saved = os.environ.pop("RLM_MODEL_API_KEY", None)
    saved2 = os.environ.pop("OPENROUTER_API_KEY", None)
    try:
        out2 = gs.build_verify_render(p)
        assert out2["verdict"] == "FAIL"
        assert "visual_inspection" not in out2
        print("OK: spatial critique fails OPEN when vision is unavailable (no crash, no note)")
    finally:
        if saved is not None:
            os.environ["RLM_MODEL_API_KEY"] = saved
        if saved2 is not None:
            os.environ["OPENROUTER_API_KEY"] = saved2


def _run_all():
    fns = [test_coherent_assembly_passes_coherence, test_floating_part_fails_named,
           test_single_solid_unchanged, test_bbox_is_output_not_gate,
           test_fidelity_pass_mints_token, test_fidelity_reject_is_advisory_still_tokens,
           test_fidelity_unavailable_fails_open, test_blob_with_dropped_features_is_only_needs_review,
           test_fused_chair_passes_geometry, test_offset_along_normal_preserves_contact,
           test_cluster_relative_prescriptive_diagnostic, test_eyes_in_loop_visual_inspection]
    for fn in fns:
        fn()
    print(f"\nALL {len(fns)} PHASE-1 TESTS PASSED")


if __name__ == "__main__":
    _run_all()
