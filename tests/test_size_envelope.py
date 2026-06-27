"""
P5 (deterministic): an EXPLICIT user-stated dimension becomes a HARD max-envelope gate (a
non-negotiable) — a grossly oversized model FAILs with an actionable cause; a within-limit model
PASSes; no stated dimension -> no gate at all (fail-open, proportions stay advisory).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))
os.environ.setdefault("PRIMITIVES_JSON_DATA", (ROOT / "schemas" / "primitives.json").read_text())
os.environ.setdefault("RLM_MODEL_API_KEY", "dummy")

import orchestrator as orch       # noqa: E402
import kernel                     # noqa: E402
import verify as verify_mod       # noqa: E402


def _reqs():
    return {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []}


def _box_plan(side):
    return {"title": "size box", "assembly_kind": "single_solid",
            "overall_dimensions": {"width": side, "length": side, "height": side},
            "engineering_requirements": _reqs(), "assumptions": [], "clarifications": [],
            "primitives_sequence": [{"sequence_id": 1, "name": "b", "primitive_type": "box",
                                     "parameters": {"length": side, "width": side, "height": side},
                                     "operation": "new", "rationale": "a sized box for the envelope test"}]}


def test_extract_size_constraint():
    c = orch._extract_size_constraint("a 100 mm diameter impeller", [])
    assert c and 113 <= c["max_extent_mm"] <= 116, c          # 100 * 1.15
    c2 = orch._extract_size_constraint("design a chair", [])  # no explicit dimension
    assert c2 is None, c2
    c3 = orch._extract_size_constraint("a bracket", [{"question": "size?", "answer": "fit within 20 cm"}])
    assert c3 and 228 <= c3["max_extent_mm"] <= 232, c3       # 200 * 1.15
    print("PASS size constraint extracted only from explicit numeric dimensions (fail-open otherwise)")


def test_within_envelope_passes():
    res = kernel.build_plan(_box_plan(50))
    assert res["ok"], res
    rep = verify_mod.verify_solid(res["solid"], plan=_box_plan(50),
                                  size_constraint={"max_extent_mm": 60.0, "source": "60 mm"})
    se = next((c for c in rep["checks"] if c["name"] == "size_envelope"), None)
    assert se is not None and se["passed"], se
    assert rep["verdict"] == "PASS", rep.get("localized_fix")
    print("PASS a model within the stated envelope passes the size gate")


def test_gross_oversize_fails():
    res = kernel.build_plan(_box_plan(50))
    assert res["ok"], res
    rep = verify_mod.verify_solid(res["solid"], plan=_box_plan(50),
                                  size_constraint={"max_extent_mm": 30.0, "source": "30 mm"})
    se = next((c for c in rep["checks"] if c["name"] == "size_envelope"), None)
    assert se is not None and not se["passed"], se
    assert rep["verdict"] == "FAIL", "a grossly oversized model must FAIL the envelope gate"
    assert "EXCEEDS" in se["detail"], se["detail"]
    print("PASS a grossly oversized model FAILs the size gate (actionable)")


def test_no_constraint_no_check():
    res = kernel.build_plan(_box_plan(50))
    rep = verify_mod.verify_solid(res["solid"], plan=_box_plan(50))   # no size_constraint
    assert not any(c["name"] == "size_envelope" for c in rep["checks"]), "no constraint -> no gate"
    assert rep["verdict"] == "PASS", rep.get("localized_fix")
    print("PASS no stated dimension -> no size gate (fail-open)")


if __name__ == "__main__":
    test_extract_size_constraint()
    test_within_envelope_passes()
    test_gross_oversize_fails()
    test_no_constraint_no_check()
    print("\nALL size-envelope (P5) tests passed.")
