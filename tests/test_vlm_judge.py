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
