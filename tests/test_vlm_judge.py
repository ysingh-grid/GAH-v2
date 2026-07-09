from tools.vlm_judge import _format_metrics, _format_verdict, _read_json


def test_read_json_accepts_plain_json():
    assert _read_json('{"passed": true, "feedback": "ok"}')["passed"] is True


def test_format_metrics_renders_structural_signals():
    block = _format_metrics(
        {
            "bounding_box": {"xmin": -20, "xmax": 20, "ymin": -20, "ymax": 20, "zmin": 0, "zmax": 60},
            "volume_mm3": 53500,
            "solid_fraction": 0.559,
            "section_profile": {"X": [1.0, 0.37, 0.37, 0.37, 1.0], "Y": None, "Z": [1.0, 0.51, 0.51, 0.51, 0.51]},
        }
    )
    assert "solid_fraction = 0.559" in block
    assert "hollow/open" in block  # <= 0.6 hint
    assert "section_fill" in block
    assert "X: [1.0, 0.37, 0.37, 0.37, 1.0]" in block
    assert "Z: [1.0, 0.51" in block


def test_format_metrics_flags_solid_block():
    block = _format_metrics({"volume_mm3": 100, "solid_fraction": 0.98})
    assert "≈solid block" in block


def test_format_metrics_omits_absent_structural_signals():
    # Backward compatible: a metrics dict without the new keys still renders,
    # and does not emit empty solid_fraction / section_fill lines.
    block = _format_metrics({"volume_mm3": 100, "num_components": 1})
    assert "solid_fraction" not in block
    assert "section_fill" not in block


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
