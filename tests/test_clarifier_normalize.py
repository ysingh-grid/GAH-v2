"""
P4 (deterministic): vague clarifier answers normalize to a recorded default, so downstream intent is
deterministic no matter how a user phrases "I don't care"; concrete answers pass through unchanged.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PRIMITIVES_JSON_DATA", (ROOT / "schemas" / "primitives.json").read_text())
os.environ.setdefault("RLM_MODEL_API_KEY", "dummy")

import orchestrator as orch       # noqa: E402

N = orch._normalize_clarification_answer
DEF = "use sensible standard defaults"


def test_blank_dropped():
    assert N("") is None and N("   ") is None and N(None) is None
    print("PASS blank answer -> dropped (agent uses defaults)")


def test_vague_normalized():
    for v in ("idk", "I don't know", "not sure", "dunno", "any", "whatever",
              "standard", "default", "defaults", "use standard defaults",
              "use sensible defaults", "you decide", "n/a"):
        assert N(v) == DEF, f"{v!r} should normalize to the default, got {N(v)!r}"
    print("PASS vague answers normalize to the recorded default")


def test_concrete_unchanged():
    for a in ("100 mm diameter", "7", "mounted on a wall", "aluminium, anodized"):
        assert N(a) == a, f"concrete answer {a!r} must pass through unchanged, got {N(a)!r}"
    print("PASS concrete answers pass through unchanged")


if __name__ == "__main__":
    test_blank_dropped()
    test_vague_normalized()
    test_concrete_unchanged()
    print("\nALL clarifier-normalize (P4) tests passed.")
