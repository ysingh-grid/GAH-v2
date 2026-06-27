"""
A3 (deterministic, host-enforced) tool tolerance for the THREE observed agent mistakes:
  - build__verify_render (double underscore) registered as an alias of build_verify_render;
  - the PASS return carries the token under BOTH 'verification_token' and 'token';
  - an invented render_format kwarg is accepted and ignored (does not raise).
Runs offline. (This neutralizes only the OBSERVED mistakes; novel typos still fail because
tool-name resolution lives in fast-rlm, which we do not modify.)
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cad_kernel import geometry_server as gs
from cad_kernel import attestation


def _valid_plan():
    return {
        "title": "valid single box",
        "overall_dimensions": {"width": 50, "length": 50, "height": 50},
        "engineering_requirements": {"functional": [], "environmental_thermal": [],
                                     "structural": [], "manufacturing_cost": []},
        "assumptions": [],
        "primitives_sequence": [
            {"sequence_id": 1, "name": "body", "primitive_type": "box",
             "parameters": {"length": 50, "width": 50, "height": 50}, "operation": "new",
             "rationale": "a single sound box used for tool-tolerance checks"},
        ],
    }


def test_alias_registered():
    # Both the canonical name and the double-underscore alias must exist as module attributes.
    assert hasattr(gs, "build_verify_render"), "build_verify_render missing"
    assert hasattr(gs, "build__verify_render"), "build__verify_render alias missing"
    assert hasattr(gs, "_build_verify_render_impl"), "shared impl missing"
    print("PASS alias build__verify_render is registered")


def test_render_format_tolerated():
    # The invented render_format kwarg must be accepted and ignored, not raise.
    out = gs._build_verify_render_impl(_valid_plan(), render_format="obj")
    assert isinstance(out, dict), out
    assert out.get("stage") != "validate", out
    print("PASS render_format kwarg tolerated (ignored, no error)")


def test_dual_token_key():
    # With a signing secret present, a clean PASS mints the token under BOTH keys, equal.
    os.environ[attestation.SECRET_ENV_VAR] = "test-secret-aaaaaaaaaaaaaaaa"
    try:
        out = gs._build_verify_render_impl(_valid_plan())
    finally:
        os.environ.pop(attestation.SECRET_ENV_VAR, None)
    assert out.get("verdict") == "PASS", out
    assert attestation.TOKEN_FIELD in out, out
    assert "token" in out, out
    assert out["token"] == out[attestation.TOKEN_FIELD], out
    print("PASS token exposed under both 'verification_token' and 'token' (equal)")


if __name__ == "__main__":
    test_alias_registered()
    test_render_format_tolerated()
    test_dual_token_key()
    print("\nALL A3 tool-tolerance tests passed.")
