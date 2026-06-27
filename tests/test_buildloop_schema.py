"""
A1 (deterministic, host-enforced): build_verify_render now validates the plan against the SAME
GeometryPlan contract the FINAL gate uses, IN-LOOP. A schema-invalid plan (e.g. pattern+new) is
rejected on submission with the concrete cause + the working construction — it can no longer
"pass geometry" and then be un-FINAL-able (the trap that made a chair run loop 9x then fake a
token). These tests run fully offline (kernel/verify/schema; no vision endpoint).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cad_kernel import geometry_server as gs


def _reqs():
    return {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []}


def _pattern_new_plan():
    """A radial pattern on a step whose operation is 'new' — forbidden by _validate_patterns."""
    return {
        "title": "pattern-new invalid",
        "overall_dimensions": {"width": 100, "length": 100, "height": 100},
        "engineering_requirements": _reqs(),
        "assumptions": [],
        "primitives_sequence": [
            {"sequence_id": 1, "name": "hub", "primitive_type": "cylinder",
             "parameters": {"radius": 20, "height": 40}, "operation": "new",
             "rationale": "central hub for the radial test"},
            {"sequence_id": 2, "name": "legs", "primitive_type": "box",
             "parameters": {"length": 80, "width": 20, "height": 15}, "operation": "new",
             "pattern": {"kind": "radial", "count": 5, "axis": "z", "center": [0, 0, 0]},
             "rationale": "five legs as separate bodies via a radial pattern (invalid usage)"},
        ],
    }


def _nonsequential_plan():
    return {
        "title": "non-sequential ids",
        "overall_dimensions": {"width": 100, "length": 100, "height": 100},
        "engineering_requirements": _reqs(),
        "assumptions": [],
        "primitives_sequence": [
            {"sequence_id": 1, "name": "a", "primitive_type": "box",
             "parameters": {"length": 50, "width": 50, "height": 50}, "operation": "new",
             "rationale": "first body for the sequence-id test"},
            {"sequence_id": 3, "name": "b", "primitive_type": "box",
             "parameters": {"length": 20, "width": 20, "height": 20}, "operation": "join",
             "rationale": "second body with a deliberately skipped sequence id"},
        ],
    }


def _valid_plan():
    return {
        "title": "valid single box",
        "overall_dimensions": {"width": 50, "length": 50, "height": 50},
        "engineering_requirements": _reqs(),
        "assumptions": [],
        "primitives_sequence": [
            {"sequence_id": 1, "name": "body", "primitive_type": "box",
             "parameters": {"length": 50, "width": 50, "height": 50}, "operation": "new",
             "rationale": "a single sound box that should pass validation"},
        ],
    }


def test_pattern_new_rejected():
    out = gs._build_verify_render_impl(_pattern_new_plan())
    assert out.get("stage") == "validate", out
    assert out.get("ok") is False, out
    assert "verification_token" not in out and "token" not in out, out
    na = (out.get("next_action") or "").lower()
    assert "pattern" in na, na
    assert "per-instance" in na or "explicit" in na, na
    print("PASS pattern+new rejected in-loop with actionable hint")


def test_nonsequential_rejected():
    out = gs._build_verify_render_impl(_nonsequential_plan())
    assert out.get("stage") == "validate" and out.get("ok") is False, out
    assert "verification_token" not in out and "token" not in out, out
    print("PASS non-sequential ids rejected in-loop")


def test_valid_plan_proceeds():
    out = gs._build_verify_render_impl(_valid_plan())
    # A valid plan must NOT be short-circuited at validation — it proceeds to build/verify.
    assert out.get("stage") != "validate", out
    assert out.get("stage") in ("build", "verify"), out
    print("PASS valid plan proceeds past in-loop validation")


if __name__ == "__main__":
    test_pattern_new_rejected()
    test_nonsequential_rejected()
    test_valid_plan_proceeds()
    print("\nALL A1 build-loop schema tests passed.")
