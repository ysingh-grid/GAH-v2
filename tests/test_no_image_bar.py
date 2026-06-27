"""
P2 (deterministic): the no-image fidelity bar is STRENGTHENED by the form brief. We verify the
machinery exists (FORM_BRIEF_ENV + the brief-grounded system prompt) and that critique() stays
FAIL-OPEN (never crashes) on the brief-grounded path when no model is available — fidelity remains
advisory and the with-image grounded path is untouched.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))
os.environ.setdefault("PRIMITIVES_JSON_DATA", (ROOT / "schemas" / "primitives.json").read_text())

import fidelity as F             # noqa: E402

_PNG = ROOT / "tests" / "_p2_probe.png"


def _make_png():
    # 1x1 PNG so _img_block can read a file (the brief-grounded branch reads images before the model).
    import base64
    data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    _PNG.write_bytes(data)


def test_brief_grounded_machinery_exists():
    assert hasattr(F, "FORM_BRIEF_ENV") and F.FORM_BRIEF_ENV == "FORGECAD_FORM_BRIEF"
    assert hasattr(F, "_SYSTEM_INTENT_BRIEF") and "INTENDED FORM BRIEF" in F._SYSTEM_INTENT_BRIEF
    assert "blocky" in F._SYSTEM_INTENT_BRIEF.lower()
    print("PASS the brief-grounded no-image bar machinery exists")


def test_critique_failopen_with_brief_no_model():
    # With a form brief set but no model, the brief-grounded no-image branch must FAIL-OPEN to
    # 'unavailable' (advisory) — never crash, never block.
    _make_png()
    os.environ[F.FORM_BRIEF_ENV] = "hub (cone) + 7 twisted blades + central bore"
    saved = os.environ.pop("RLM_MODEL_API_KEY", None)
    os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ.pop(F.STUB_ENV, None)
    os.environ.pop(F.REFERENCE_ENV, None)
    try:
        v = F.critique([str(_PNG)], intent="a centrifugal impeller")
        assert v["status"] == "unavailable", v
    finally:
        os.environ.pop(F.FORM_BRIEF_ENV, None)
        if saved is not None:
            os.environ["RLM_MODEL_API_KEY"] = saved
        try:
            _PNG.unlink()
        except Exception:
            pass
    print("PASS no-image brief-grounded critique fail-opens to 'unavailable' (advisory, no crash)")


if __name__ == "__main__":
    test_brief_grounded_machinery_exists()
    test_critique_failopen_with_brief_no_model()
    print("\nALL no-image-bar (P2) tests passed.")
