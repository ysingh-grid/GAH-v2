"""
test_phase0_token_gate.py — proves Phase 0's deterministic spine is UNSKIPPABLE,
end to end at the host layer (no live LLM needed).

What this guards (the "remove-it test"): if the token mechanism were removed, an agent
could FINAL an unbuilt/unverified plan and the run would proceed on un-proven geometry.
These tests reproduce the chair-style plan and assert:
  1. A genuine build_verify_render PASS mints a token that authenticates for THAT plan.
  2. The orchestrator gate logic ACCEPTS a token-carrying FINAL and REJECTS a tokenless,
     forged, or altered-plan FINAL — i.e. skipping verification cannot complete a run.
  3. The attempt ledger escalates on a re-submitted identical failing plan.
  4. The native primitive tool, the JSON file, and the Pydantic schema share one source.
"""

import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))

# Single source of truth must be present in env before the native tool / kernel import.
PRIMS_TEXT = (ROOT / "schemas" / "primitives.json").read_text()
os.environ["PRIMITIVES_JSON_DATA"] = PRIMS_TEXT
TEST_SECRET = "phase0_test_secret_deadbeef"
os.environ["FORGECAD_RUN_SECRET"] = TEST_SECRET

from cad_kernel import attestation  # noqa: E402
import geometry_server as gs        # noqa: E402


def _chair_like_pass_plan():
    """A small, genuinely sound single_solid — stands in for a verified part. A single box
    with exact declared dims is a deterministic PASS; the test is about the token gate, not
    geometric realism."""
    return {
        "title": "Sound base block",
        "assembly_kind": "single_solid",
        "overall_dimensions": {"width": 60, "length": 40, "height": 20},
        "engineering_requirements": {"functional": [], "environmental_thermal": [],
                                     "structural": [], "manufacturing_cost": []},
        "assumptions": [], "clarifications": [],
        "primitives_sequence": [
            {"sequence_id": 1, "name": "base", "primitive_type": "box",
             "parameters": {"length": 60, "width": 40, "height": 20},
             "operation": "new", "rationale": "the single sound base block for the test"},
        ],
    }


_PASS_BBOX = [60, 40, 20]


def _disconnected_fail_plan():
    """single_solid expecting 1 component, but two boxes are far apart -> FAIL (2 comps)."""
    return {
        "title": "Disconnected", "assembly_kind": "single_solid",
        "overall_dimensions": {"width": 100, "length": 10, "height": 10},
        "engineering_requirements": {"functional": [], "environmental_thermal": [],
                                     "structural": [], "manufacturing_cost": []},
        "assumptions": [], "clarifications": [],
        "primitives_sequence": [
            {"sequence_id": 1, "name": "a", "primitive_type": "box",
             "parameters": {"length": 10, "width": 10, "height": 10},
             "operation": "new", "position": [0, 0, 0], "rationale": "first floating body"},
            {"sequence_id": 2, "name": "b", "primitive_type": "box",
             "parameters": {"length": 10, "width": 10, "height": 10},
             "operation": "new", "position": [80, 0, 0], "rationale": "second floating body far away"},
        ],
    }


def _simulate_gate(plan_with_token: dict, secret: str = TEST_SECRET):
    """Reproduce the orchestrator's TOKEN GATE in isolation: pop the token, authenticate.
    Returns (accepted: bool, plan_without_token: dict)."""
    p = dict(plan_with_token)
    token = p.pop(attestation.TOKEN_FIELD, None)
    return attestation.verify_token(secret, p, token), p


def test_pass_mints_authentic_token():
    plan = _chair_like_pass_plan()
    r = gs.build_verify_render(plan, declared_bbox=_PASS_BBOX, expected_components=1, render=False)
    assert r["verdict"] == "PASS", r
    assert attestation.TOKEN_FIELD in r, "PASS must mint a token"
    assert attestation.verify_token(TEST_SECRET, plan, r[attestation.TOKEN_FIELD])
    print("OK: genuine PASS mints an authentic token")


def test_gate_accepts_verified_final():
    plan = _chair_like_pass_plan()
    r = gs.build_verify_render(plan, declared_bbox=_PASS_BBOX, expected_components=1, render=False)
    final_plan = dict(plan)
    final_plan[attestation.TOKEN_FIELD] = r[attestation.TOKEN_FIELD]  # what the agent FINALs
    accepted, stripped = _simulate_gate(final_plan)
    assert accepted, "a properly verified+token-carrying FINAL must be accepted"
    assert attestation.TOKEN_FIELD not in stripped, "token must be stripped before pydantic/plan_store"
    print("OK: gate accepts a verified, token-carrying FINAL and strips the token")


def test_gate_rejects_tokenless_final():
    # The exact observed failure: agent drafts a plan and FINALs WITHOUT verifying.
    plan = _chair_like_pass_plan()  # even a sound plan must be rejected if unverified
    accepted, _ = _simulate_gate(plan)  # no token embedded
    assert not accepted, "a tokenless FINAL (skipped verification) MUST be rejected"
    print("OK: gate rejects a tokenless FINAL (verification is unskippable)")


def test_gate_rejects_forged_and_altered():
    plan = _chair_like_pass_plan()
    r = gs.build_verify_render(plan, declared_bbox=_PASS_BBOX, expected_components=1, render=False)
    real = r[attestation.TOKEN_FIELD]
    # forged token
    forged = dict(plan); forged[attestation.TOKEN_FIELD] = "0" * 64
    assert not _simulate_gate(forged)[0], "forged token must be rejected"
    # real token but plan altered after verifying (dimension bumped)
    altered = dict(plan)
    altered["primitives_sequence"] = json.loads(json.dumps(plan["primitives_sequence"]))
    altered["primitives_sequence"][0]["parameters"]["length"] = 61
    altered[attestation.TOKEN_FIELD] = real
    assert not _simulate_gate(altered)[0], "token must not validate for an altered plan"
    print("OK: gate rejects forged tokens and post-verification plan tampering")


def test_fail_returns_no_token_and_ledger_escalates():
    bad = _disconnected_fail_plan()
    r1 = gs.build_verify_render(bad, declared_bbox=[100, 10, 10], expected_components=1, render=False)
    assert r1["verdict"] == "FAIL"
    assert attestation.TOKEN_FIELD not in r1, "FAIL must not mint a token"
    assert "next_action" in r1
    r2 = gs.build_verify_render(bad, declared_bbox=[100, 10, 10], expected_components=1, render=False)
    assert "FORBIDDEN MOVE" in r2["next_action"], r2["next_action"]
    print("OK: FAIL yields no token; identical resubmission escalates in the ledger")


def test_single_source_of_truth():
    from tools.get_primitives import get_primitives_library
    from schemas.geometry_plan import PRIMITIVES_REGISTRY
    native = get_primitives_library()
    src = json.loads(PRIMS_TEXT)
    assert native == src, "native tool must equal primitives.json"
    assert set(PRIMITIVES_REGISTRY) == set(src), "schema registry must equal primitives.json keys"
    # the inlined dict must be gone (no primitive templates hardcoded in the tool source)
    tool_src = (ROOT / "tools" / "get_primitives.py").read_text()
    assert '"template"' not in tool_src and "'template'" not in tool_src, "inlined dict must be deleted"
    print("OK: one source of truth (primitives.json) across native tool + schema; no inlined dict")


def _run_all():
    fns = [test_pass_mints_authentic_token, test_gate_accepts_verified_final,
           test_gate_rejects_tokenless_final, test_gate_rejects_forged_and_altered,
           test_fail_returns_no_token_and_ledger_escalates, test_single_source_of_truth]
    for fn in fns:
        fn()
    print(f"\nALL {len(fns)} PHASE-0 TOKEN-GATE TESTS PASSED")


if __name__ == "__main__":
    _run_all()
