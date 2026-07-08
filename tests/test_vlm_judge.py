from tools.vlm_judge import _format_metrics, _format_verdict, _read_json


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


# ── Task 3: grounded verifier (metrics + checklist + per-feature findings) ────


def test_format_metrics_renders_bbox_volume_components():
    block = _format_metrics(
        {
            "bounding_box": {
                "xmin": -50, "xmax": 50, "ymin": -30, "ymax": 30, "zmin": 0, "zmax": 8,
            },
            "volume_mm3": 48000.0,
            "num_components": 2,
            "is_watertight": True,
        }
    )
    assert "bbox_size_mm = 100.0 x 60.0 x 8.0" in block
    assert "volume_mm3 = 48000.0" in block
    assert "num_components = 2" in block
    assert "watertight = True" in block


def test_format_verdict_carries_feature_findings_and_object_ok():
    verdict = _format_verdict(
        {
            "passed": False,
            "object_ok": True,
            "failure_type": "wrong_proportion",
            "feature_findings": [
                {"feature": "side frames", "status": "wrong", "note": "too thin"}
            ],
            "feedback": "frames read as rails",
        },
        "render.png",
    )
    assert verdict["object_ok"] is True
    assert verdict["feature_findings"][0]["feature"] == "side frames"
    # legacy keys still present + formatted
    assert verdict["failure_stage"] == "visual_mismatch"
    assert verdict["feedback"].startswith("[visual_failure:wrong_proportion]")


def test_format_verdict_defaults_feature_findings_to_empty_list():
    verdict = _format_verdict({"passed": True}, "render.png")
    assert verdict["feature_findings"] == []
    assert verdict["object_ok"] is True  # defaults to `passed` when omitted


def test_judge_geometry_render_grounds_model_with_checklist_and_metrics(tmp_path, monkeypatch):
    """The checklist + metrics must reach the model text, and findings flow back."""
    png = tmp_path / "r.png"
    png.write_bytes(b"\x89PNG\r\n")

    captured: dict = {}

    def fake_call_vlm(prompt, render_png, last_replan_feedback, metrics=None, feature_checklist=""):
        captured["prompt"] = prompt
        captured["metrics"] = metrics
        captured["feature_checklist"] = feature_checklist
        return (
            '{"passed": false, "object_ok": false, "failure_type": "missing_feature",'
            ' "feature_findings": [{"feature": "hinge pins", "status": "missing",'
            ' "note": "no pins visible; add two 5mm cylinders spanning the frames"}],'
            ' "feedback": "hinge pins missing"}'
        )

    monkeypatch.setattr("tools.vlm_judge._call_vlm", fake_call_vlm)

    from tools.vlm_judge import judge_geometry_render

    verdict = judge_geometry_render(
        prompt="a foldable laptop stand",
        render_png=str(png),
        metrics={
            "bounding_box": {"xmin": 0, "xmax": 100, "ymin": 0, "ymax": 60, "zmin": 0, "zmax": 8}
        },
        feature_checklist="Required-feature checklist:\n- [ ] two hinge pins",
    )
    assert captured["metrics"] is not None
    assert "hinge pins" in captured["feature_checklist"]
    assert verdict["failure_stage"] == "visual_mismatch"
    assert verdict["feature_findings"][0]["feature"] == "hinge pins"


def test_verify_geometry_forwards_metrics_and_checklist(monkeypatch):
    """Regression: verify_geometry used to DROP metrics; it must now forward them."""
    import importlib

    seen: dict = {}

    def fake_judge(*, prompt, render_png, last_replan_feedback, metrics, feature_checklist):
        seen["metrics"] = metrics
        seen["feature_checklist"] = feature_checklist
        return {"passed": True}

    # tools/__init__.py re-exports the verify_geometry FUNCTION, shadowing the
    # submodule name — so patch the real module object, not `tools.verify_geometry`.
    vg_module = importlib.import_module("tools.verify_geometry")
    monkeypatch.setattr(vg_module, "judge_geometry_render", fake_judge)

    vg_module.verify_geometry(
        prompt="p",
        code="ignored",
        metrics={"volume_mm3": 123.0},
        render_png="r.png",
        feature_checklist="Required-feature checklist:\n- [ ] a boss",
    )
    assert seen["metrics"] == {"volume_mm3": 123.0}  # no longer dropped
    assert "a boss" in seen["feature_checklist"]
