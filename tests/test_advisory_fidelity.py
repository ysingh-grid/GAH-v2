"""
Task 1 + Task 2 (deterministic, offline via fidelity STUB):
  - Fidelity is ADVISORY: a sound+coherent model with a fidelity REJECT still returns verdict PASS,
    still mints a verification_token, and is tagged trust_tier='needs_review' (was: verdict flipped
    to FAIL, no token — the bug that discarded a sound chair).
  - A fidelity PASS yields trust_tier='certified'.
  - The best-candidate checkpoint ranks fidelity-pass(2) above sound+coherent(1).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cad_kernel import geometry_server as gs
from cad_kernel import fidelity as fid
from cad_kernel.attestation import SECRET_ENV_VAR, verify_token


def _reqs():
    return {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []}


def _box_plan():
    return {"title": "box", "assembly_kind": "single_solid",
            "overall_dimensions": {"width": 40, "length": 40, "height": 40},
            "engineering_requirements": _reqs(), "assumptions": [], "clarifications": [],
            "primitives_sequence": [
                {"sequence_id": 1, "name": "b", "primitive_type": "box",
                 "parameters": {"length": 40, "width": 40, "height": 40}, "operation": "new",
                 "rationale": "a single sound box for the advisory-fidelity test"}]}


def test_fidelity_reject_still_passes_and_tokens():
    os.environ[SECRET_ENV_VAR] = "testsecret"
    os.environ[fid.STUB_ENV] = json.dumps(
        {"recognizable": False, "missing_major_features": ["too blocky vs reference"],
         "present_features": []})
    try:
        out = gs._build_verify_render_impl(_box_plan())
    finally:
        os.environ.pop(fid.STUB_ENV, None)
    assert out["verdict"] == "PASS", out                       # fidelity no longer flips the verdict
    assert out.get("trust_tier") == "needs_review", out
    tok = out.get("verification_token")
    assert tok, "token MUST mint on geometry+coherence PASS even when fidelity rejects"
    assert verify_token("testsecret", _box_plan(), tok), "minted token must authenticate the plan"
    print("PASS fidelity REJECT → verdict PASS + token + trust_tier=needs_review (sound chair delivered)")


def test_fidelity_pass_is_certified():
    os.environ[SECRET_ENV_VAR] = "testsecret"
    os.environ[fid.STUB_ENV] = json.dumps(
        {"recognizable": True, "missing_major_features": [], "present_features": ["box"]})
    try:
        out = gs._build_verify_render_impl(_box_plan())
    finally:
        os.environ.pop(fid.STUB_ENV, None)
    assert out["verdict"] == "PASS", out
    assert out.get("trust_tier") == "certified", out
    assert out.get("verification_token"), out
    print("PASS fidelity PASS → trust_tier=certified")


def test_checkpoint_ranking_prefers_fidelity():
    ckpt = tempfile.mktemp(suffix=".json")
    saved_file, saved_best = gs._CHECKPOINT_FILE, dict(gs._BEST)
    gs._CHECKPOINT_FILE = ckpt
    gs._BEST = {"rank": -1}
    try:
        gs._update_best({"title": "sound_only_1"}, [1, 1, 1], None, "needs_review", None, False)
        assert json.load(open(ckpt))["rank"] == 1
        gs._update_best({"title": "fidelity_pass"}, [1, 1, 1], None, "certified",
                        {"status": "pass"}, True)
        rec = json.load(open(ckpt))
        assert rec["rank"] == 2 and rec["plan"]["title"] == "fidelity_pass", rec
        # a later sound-only candidate must NOT displace a banked fidelity-pass candidate
        gs._update_best({"title": "sound_only_2"}, [1, 1, 1], None, "needs_review", None, False)
        rec = json.load(open(ckpt))
        assert rec["plan"]["title"] == "fidelity_pass", rec
        print("PASS checkpoint ranks fidelity-pass above sound+coherent")
    finally:
        gs._CHECKPOINT_FILE, gs._BEST = saved_file, saved_best
        os.path.exists(ckpt) and os.remove(ckpt)


if __name__ == "__main__":
    test_fidelity_reject_still_passes_and_tokens()
    test_fidelity_pass_is_certified()
    test_checkpoint_ranking_prefers_fidelity()
    print("\nALL advisory-fidelity + checkpoint-ranking tests passed.")
