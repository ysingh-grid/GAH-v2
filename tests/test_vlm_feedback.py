"""
B3 (FLAGGED non-deterministic in impact): VLM feedback robustness + render cues. These tests are
deterministic via STUBS — they verify the PLUMBING (structured feedback flows + back-compat,
render produces a PNG with orientation cues, spatial critique fires on any geometry failure). They
do NOT and CANNOT verify that orientation is actually fixed — that remains the perceptual loop and
depends on a live vision endpoint.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cad_kernel import fidelity as fid
from cad_kernel import kernel, render as render_mod
from cad_kernel import geometry_server as gs


def _reqs():
    return {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []}


def test_verdict_structured_and_backcompat():
    # structured per-part feedback (list of dicts)
    structured = {"recognizable": True,
                  "missing_major_features": [{"part": "seat", "issue": "flat slab", "fix": "contour it"}],
                  "present_features": ["legs"], "notes": "ok"}
    v = fid._verdict_from_payload(structured)
    assert v["status"] == "reject", v
    assert v["missing_major_features"] == ["seat: flat slab -> contour it"], v["missing_major_features"]
    assert v["missing_features_structured"] == structured["missing_major_features"], v
    # back-compat: plain string list still works and stays as strings
    plain = {"recognizable": True, "missing_major_features": ["no casters"], "present_features": []}
    v2 = fid._verdict_from_payload(plain)
    assert v2["missing_major_features"] == ["no casters"], v2
    assert v2["status"] == "reject", v2
    print("PASS verdict handles structured per-part feedback AND back-compat string list")


def test_critique_stub_structured():
    stub = json.dumps({"recognizable": False,
                       "missing_major_features": [{"part": "backrest", "issue": "missing", "fix": "add it"}],
                       "notes": "n"})
    os.environ[fid.STUB_ENV] = stub
    try:
        out = fid.critique(["/nonexistent.png"], part_names=["seat", "backrest"])
    finally:
        os.environ.pop(fid.STUB_ENV, None)
    assert out["status"] == "reject", out
    assert out["missing_major_features"] == ["backrest: missing -> add it"], out
    print("PASS critique() flattens structured stub feedback to list[str]")


def test_render_produces_png_with_cues():
    plan = {"title": "box", "assembly_kind": "single_solid",
            "overall_dimensions": {"width": 30, "length": 30, "height": 30},
            "engineering_requirements": _reqs(), "assumptions": [],
            "primitives_sequence": [
                {"sequence_id": 1, "name": "b", "primitive_type": "box",
                 "parameters": {"length": 30, "width": 30, "height": 30}, "operation": "new",
                 "rationale": "single box for the render-cue test"}]}
    res = kernel.build_plan(plan)
    assert res["ok"], res
    out_png = tempfile.mktemp(suffix=".png")
    try:
        p = render_mod.render_solid(res["solid"], out_png)
        assert os.path.exists(p) and os.path.getsize(p) > 0, p
        print("PASS render_solid produces a non-empty PNG (named views + axis triad)")
    finally:
        os.path.exists(out_png) and os.remove(out_png)


def test_spatial_fires_on_geometry_failure():
    # two parts far apart -> coherence FAIL (geom_pass False) -> spatial critique must fire (stubbed)
    plan = {"title": "disconnected", "assembly_kind": "assembly",
            "overall_dimensions": {"width": 100, "length": 100, "height": 100},
            "engineering_requirements": _reqs(), "assumptions": [],
            "primitives_sequence": [
                {"sequence_id": 1, "name": "a", "primitive_type": "box",
                 "parameters": {"length": 20, "width": 20, "height": 20}, "operation": "new",
                 "part": "a", "position": [0, 0, 0], "rationale": "first isolated part for spatial test"},
                {"sequence_id": 2, "name": "b", "primitive_type": "box",
                 "parameters": {"length": 20, "width": 20, "height": 20}, "operation": "new",
                 "part": "b", "position": [1000, 0, 0], "rationale": "second far-away isolated part"}]}
    os.environ[fid.SPATIAL_STUB_ENV] = "part 'b' is floating far out along +X, disconnected from 'a'"
    try:
        out = gs._build_verify_render_impl(plan)
    finally:
        os.environ.pop(fid.SPATIAL_STUB_ENV, None)
    assert out.get("verdict") == "FAIL", out
    assert out.get("visual_inspection"), out
    assert "VISUAL INSPECTION" in (out.get("next_action") or ""), out.get("next_action")
    print("PASS spatial critique fires on geometry/coherence failure and reaches next_action")


if __name__ == "__main__":
    test_verdict_structured_and_backcompat()
    test_critique_stub_structured()
    test_render_produces_png_with_cues()
    test_spatial_fires_on_geometry_failure()
    print("\nALL B3 VLM-feedback/render-cue tests passed.")
