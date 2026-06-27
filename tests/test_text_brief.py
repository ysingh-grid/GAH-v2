"""
P1 (deterministic): a no-image run must still get an upfront FORM BRIEF — the platform imagines the
object from the TEXT description (multimodal model in text mode), giving the same structural/
orientation guidance a reference image would. Fail-open: no model -> None (run proceeds unchanged).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))
os.environ.setdefault("PRIMITIVES_JSON_DATA", (ROOT / "schemas" / "primitives.json").read_text())

import fidelity as F             # noqa: E402


def test_text_brief_returns_stub():
    os.environ[F.BRIEF_STUB_ENV] = "BRIEF: hub (cone) + 7 twisted blades (radial) + central bore"
    try:
        b = F.extract_design_brief_from_text("a centrifugal impeller",
                                             [{"question": "blades?", "answer": "7"}])
        assert b and "twisted blades" in b, b
    finally:
        os.environ.pop(F.BRIEF_STUB_ENV, None)
    print("PASS text brief returns the structured brief (stubbed)")


def test_text_brief_failopen_empty_prompt():
    os.environ.pop(F.BRIEF_STUB_ENV, None)
    assert F.extract_design_brief_from_text("", None) is None
    assert F.extract_design_brief_from_text(None, None) is None
    print("PASS text brief fail-opens to None on empty prompt")


def test_text_brief_failopen_no_model():
    # No stub + no usable API key -> the vision call fails -> None (run proceeds exactly as before).
    os.environ.pop(F.BRIEF_STUB_ENV, None)
    saved = os.environ.pop("RLM_MODEL_API_KEY", None)
    os.environ.pop("OPENROUTER_API_KEY", None)
    try:
        assert F.extract_design_brief_from_text("a 1-litre water bottle", None) is None
    finally:
        if saved is not None:
            os.environ["RLM_MODEL_API_KEY"] = saved
    print("PASS text brief fail-opens to None when no model is available")


if __name__ == "__main__":
    test_text_brief_returns_stub()
    test_text_brief_failopen_empty_prompt()
    test_text_brief_failopen_no_model()
    print("\nALL text-brief (P1) tests passed.")
