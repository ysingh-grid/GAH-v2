"""
test_reference_loop.py — deterministic tests for the reference-grounded design loop (vision STUBBED
or forced-unavailable). Covers: design-brief extraction (stub + fail-open), the grounded-critic
reference path (reads the reference image, fails OPEN with no endpoint), no-reference fallback, the
per-custom gross-scale audit, and the run_pipeline refactor. Live vision quality needs the machine.
"""

import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))
os.environ["PRIMITIVES_JSON_DATA"] = (ROOT / "schemas" / "primitives.json").read_text()
os.environ.setdefault("RLM_MODEL_API_KEY", "dummy-for-import")  # orchestrator import needs a key

import kernel                       # noqa: E402
from cad_kernel import fidelity     # noqa: E402

# a tiny dummy reference image file (content irrelevant — only the read/encode path is exercised)
_REF = ROOT / "refs" / "_test_ref.png"
_REF.parent.mkdir(exist_ok=True)
_REF.write_bytes(bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"))


def test_brief_stub_and_failopen():
    os.environ["FORGECAD_BRIEF_STUB"] = "PARTS: seat (lofted pan, horizontal); back (curved, vertical)"
    try:
        assert fidelity.extract_design_brief(str(_REF), "office chair").startswith("PARTS:")
    finally:
        os.environ.pop("FORGECAD_BRIEF_STUB", None)
    # no key, no stub -> fail-open (None), no crash
    saved = os.environ.pop("RLM_MODEL_API_KEY", None)
    try:
        assert fidelity.extract_design_brief(str(_REF), "office chair") is None
        assert fidelity.extract_design_brief("/no/such/file.png", "x") is None
    finally:
        if saved is not None:
            os.environ["RLM_MODEL_API_KEY"] = saved
    print("OK: design-brief extraction works via stub and fails open")


def test_reference_path_helper_and_grounded_failopen():
    os.environ["FORGECAD_REFERENCE_IMAGE"] = str(_REF)
    saved = os.environ.pop("RLM_MODEL_API_KEY", None)
    os.environ.pop("FORGECAD_FIDELITY_STUB", None)
    try:
        assert fidelity._reference_image_path() == str(_REF)
        # reference present + no endpoint -> grounded path reads the ref image, then fails OPEN
        v = fidelity.critique([str(_REF)], intent="office chair", measured_bbox=[100, 100, 100])
        assert v["status"] == "unavailable", v
        print("OK: grounded critic reads the reference and fails open with no endpoint")
    finally:
        os.environ.pop("FORGECAD_REFERENCE_IMAGE", None)
        if saved is not None:
            os.environ["RLM_MODEL_API_KEY"] = saved


def test_no_reference_fallback():
    os.environ.pop("FORGECAD_REFERENCE_IMAGE", None)
    assert fidelity._reference_image_path() is None
    os.environ["FORGECAD_FIDELITY_STUB"] = json.dumps({"recognizable": True, "missing_major_features": []})
    try:
        v = fidelity.critique(["/whatever.png"], intent="a box")
        assert v["status"] == "pass"  # stub short-circuits; no-reference path is intact
    finally:
        os.environ.pop("FORGECAD_FIDELITY_STUB", None)
    print("OK: with no reference image the critic falls back to the intent-only bar")


def _custom_plan(code, declared):
    return {"title": "t", "assembly_kind": "single_solid",
            "overall_dimensions": {"width": 1, "length": 1, "height": 1},
            "engineering_requirements": {"functional": [], "environmental_thermal": [],
                                         "structural": [], "manufacturing_cost": []},
            "assumptions": [], "clarifications": [],
            "primitives_sequence": [{"sequence_id": 1, "name": "c", "primitive_type": "custom",
                                     "parameters": {"shape_description": "test", "cadquery_operations": [],
                                                    "code_sketch": code, "declared_dimensions": declared},
                                     "operation": "new", "rationale": "a custom test solid here"}]}


def test_custom_scale_audit():
    # declared ~40 but the code builds 400 -> gross 10x mismatch -> clean failure
    bad = _custom_plan("result = cq.Workplane('XY').box(400,400,400)", {"size": 40})
    r = kernel.build_plan(bad)
    assert not r["ok"] and "scale mismatch" in str(r.get("steps")), r
    # declared ~40 and the code builds 40 -> passes
    good = _custom_plan("result = cq.Workplane('XY').box(40,40,40)", {"size": 40})
    r2 = kernel.build_plan(good)
    assert r2["ok"], r2
    # no declared_dimensions -> no audit (still builds)
    none = _custom_plan("result = cq.Workplane('XY').box(400,400,400)", {})
    assert kernel.build_plan(none)["ok"]
    print("OK: per-custom gross-scale audit fails 10x-off and passes a correct/undeclared custom")


def test_run_pipeline_refactor():
    import orchestrator
    assert callable(orchestrator.run_pipeline)
    assert callable(orchestrator.generate_clarification_questions)
    assert issubclass(orchestrator.PipelineError, Exception)
    print("OK: run_pipeline + generate_clarification_questions + PipelineError are exposed")


def _run_all():
    fns = [test_brief_stub_and_failopen, test_reference_path_helper_and_grounded_failopen,
           test_no_reference_fallback, test_custom_scale_audit, test_run_pipeline_refactor]
    for fn in fns:
        fn()
    print(f"\nALL {len(fns)} REFERENCE-LOOP TESTS PASSED")


if __name__ == "__main__":
    _run_all()
