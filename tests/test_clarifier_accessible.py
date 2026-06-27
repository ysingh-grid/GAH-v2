"""
P3 (deterministic): the clarifier must be usable by ANY user — it asks about the NON-NEGOTIABLES in
PLAIN language with concrete examples and an escape, and must NOT lean on engineering jargon. We lock
the role's hallmarks so it can never silently regress into a jargon-heavy bottleneck.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PRIMITIVES_JSON_DATA", (ROOT / "schemas" / "primitives.json").read_text())
os.environ.setdefault("RLM_MODEL_API_KEY", "dummy")

import orchestrator as orch       # noqa: E402


def test_clarifier_is_accessible_and_nonnegotiable_focused():
    role = orch.CLARIFIER_ROLE.lower()
    # plain-language + accessibility hallmarks
    assert "plain" in role, "must instruct plain language"
    assert "example" in role, "must give concrete example answers"
    assert ("not sure" in role) or ("standard defaults" in role), "must offer an escape"
    # the non-negotiable categories
    for cat in ("size", "count", "orient", "material"):
        assert cat in role, f"clarifier must target the non-negotiable '{cat}'"
    # must explicitly instruct to AVOID jargon (it may name jargon terms only as negative examples)
    assert "jargon" in role, "clarifier must instruct to avoid jargon"
    print("PASS clarifier is plain-language, example-driven, non-negotiable-focused, with an escape")


if __name__ == "__main__":
    test_clarifier_is_accessible_and_nonnegotiable_focused()
    print("\nALL clarifier-accessibility (P3) tests passed.")
