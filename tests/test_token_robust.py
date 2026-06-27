"""
Token robustness (deterministic): the verification token pins the AUTHORED GEOMETRY, not its
representation. A genuinely-verified plan must survive the benign edits the agent makes between
verifying and FINAL — the exact failure that silently downgraded a sound chair to a best-effort
artifact (the agent added `contains_freeform` after the token was minted, so the hash changed and
the gate discarded a real PASS; acceptance had been depending on the agent's incidental field
ordering). A REAL geometry change must still be rejected (forgery protection unchanged).
"""
import copy
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))
os.environ.setdefault("PRIMITIVES_JSON_DATA", (ROOT / "schemas" / "primitives.json").read_text())

import attestation as A            # noqa: E402

SECRET = "test_secret_123"


def _plan():
    return {"title": "Token Box", "assembly_kind": "single_solid",
            "overall_dimensions": {"width": 30, "length": 30, "height": 30},
            "engineering_requirements": {"functional": [], "environmental_thermal": [],
                                         "structural": [], "manufacturing_cost": []},
            "assumptions": [], "clarifications": [],
            "primitives_sequence": [{"sequence_id": 1, "name": "b", "primitive_type": "box",
                                     "parameters": {"length": 30, "width": 30, "height": 30},
                                     "operation": "new",
                                     "rationale": "a single test box body for token robustness"}]}


def test_token_survives_added_contains_freeform_and_measured_dims():
    # Mint WITHOUT contains_freeform (the …08-46 scenario), then FINAL a dict that ADDS
    # contains_freeform + the host-measured overall_dimensions -> the token must still authenticate.
    minted = _plan()
    assert "contains_freeform" not in minted
    tok = A.make_token(SECRET, minted)
    final = copy.deepcopy(minted)
    final["contains_freeform"] = False
    final["overall_dimensions"] = {"width": 30.0, "length": 30.0, "height": 29.97}
    assert A.verify_token(SECRET, final, tok), "benign added/derived fields must NOT break the token"
    print("PASS token survives added contains_freeform + measured overall_dimensions")


def test_token_survives_int_float_and_reserialization():
    minted = _plan()                       # ints (30)
    tok = A.make_token(SECRET, minted)
    final = json.loads(json.dumps(minted))  # full reserialization round-trip
    final["primitives_sequence"][0]["parameters"]["length"] = 30.0   # int -> float
    final["contains_freeform"] = False
    assert A.verify_token(SECRET, final, tok), "int->float / reserialization must NOT break the token"
    print("PASS token survives int->float + reserialization")


def test_token_survives_metadata_edits():
    # The 2026-06-27T16:51 impeller run: a token was minted on a PASSing plan, then before FINAL the
    # agent CHANGED the title and ADDED an assumption (pure descriptive metadata, zero geometry
    # effect). The token broke and a genuinely-verified impeller was discarded to best-effort.
    minted = _plan()
    tok = A.make_token(SECRET, minted)
    final = copy.deepcopy(minted)
    final["title"] = "Centrifugal Compressor Impeller"
    final["assumptions"] = ["Standard industrial dimensions", "Shaft diameter is 20mm"]
    final["clarifications"] = [{"question": "blade count?", "answer": "7"}]
    final["engineering_requirements"]["functional"] = ["aerodynamic flow path"]
    final["primitives_sequence"][0]["rationale"] = "the single hub body (reworded)"
    final["contains_freeform"] = False
    final["overall_dimensions"] = {"width": 30.0, "length": 30.0, "height": 29.97}
    assert A.verify_token(SECRET, final, tok), \
        "descriptive metadata edits must NOT break the geometry token"
    print("PASS token survives descriptive-metadata edits (title/assumptions/clarifications/reqs/rationale)")


def test_token_rejects_real_geometry_change():
    minted = _plan()
    tok = A.make_token(SECRET, minted)
    bad = copy.deepcopy(minted)
    bad["primitives_sequence"][0]["parameters"]["length"] = 40   # a REAL geometry change
    assert not A.verify_token(SECRET, bad, tok), "a real geometry change MUST be rejected"
    assert not A.verify_token("other_secret", minted, tok), "a wrong secret MUST be rejected"
    print("PASS token rejects a real geometry change + a wrong secret")


if __name__ == "__main__":
    test_token_survives_added_contains_freeform_and_measured_dims()
    test_token_survives_int_float_and_reserialization()
    test_token_survives_metadata_edits()
    test_token_rejects_real_geometry_change()
    print("\nALL token-robustness tests passed.")
