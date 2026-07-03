import importlib

from tools.vlm_judge import _format_verdict, _read_json


def test_read_json_accepts_plain_json():
    assert _read_json('{"passed": true, "feedback": "ok"}')["passed"] is True


def test_read_json_accepts_fenced_json():
    text = '```json\n{"passed": false, "failure_type": "missing_feature"}\n```'
    assert _read_json(text)["failure_type"] == "missing_feature"


def test_read_json_uses_first_balanced_object():
    text = '{"passed": true, "feedback": "ok"}\n}'
    assert _read_json(text)["passed"] is True


def test_format_verdict_for_pass():
    verdict = _format_verdict(
        {"passed": True, "failure_type": "missing_feature", "feedback": ""},
        "render.png",
    )

    assert verdict["passed"] is True
    assert verdict["failure_type"] == "none"
    assert verdict["feedback"] == "All constraints met."
    assert verdict["failure_stage"] == ""


def test_format_verdict_for_failure_adds_replan_classification():
    verdict = _format_verdict(
        {
            "passed": False,
            "failure_type": "missing_feature",
            "feedback": "The center bore is missing.",
        },
        "render.png",
    )

    assert verdict["passed"] is False
    assert verdict["failure_type"] == "missing_feature"
    assert verdict["failure_stage"] == "visual_mismatch"
    assert verdict["feedback"].startswith("[visual_failure:missing_feature]")


def test_verify_geometry_passes_latest_feedback_to_judge(monkeypatch):
    verify_geometry_module = importlib.import_module("tools.verify_geometry")
    calls = {}

    def fake_judge_geometry_render(prompt, render_png, last_replan_feedback=None):
        calls["args"] = (prompt, render_png, last_replan_feedback)
        return {"passed": True, "feedback": "All constraints met.", "failure_stage": ""}

    monkeypatch.setattr(verify_geometry_module, "judge_geometry_render", fake_judge_geometry_render)

    verdict = verify_geometry_module.verify_geometry(
        "make a bracket",
        {"volume_mm3": 1000},
        "render.png",
        prior_feedback=["first issue", "latest issue"],
    )

    assert verdict["passed"] is True
    assert calls["args"] == ("make a bracket", "render.png", "latest issue")
