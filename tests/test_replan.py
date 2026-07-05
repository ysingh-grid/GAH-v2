"""Unit tests for runtime/replan.py — caps, stage->skill, feedback, re-entry."""

from runtime.replan import (
    INNER_CAP,
    OUTER_CAP,
    STAGE_TO_SKILL,
    build_edit_message,
    build_feedback_message,
    cap_for_stage,
    collect_feedback_detail,
    is_exhausted,
    replan_for_edit,
    replan_with_feedback,
)
from runtime.schema import plan_from_dict

_CUBE = plan_from_dict(
    {
        "part_name": "cube",
        "steps": [{"id": "b", "primitive": "box", "operation": "base"}],
    }
)


def test_inner_stage_cap_is_five():
    assert cap_for_stage("cadquery_compile") == INNER_CAP == 5
    assert cap_for_stage("mesh_repair") == 5
    assert cap_for_stage("primitive_gap") == 5


def test_verifier_error_is_inner_not_fail_fast():
    """verifier_error (VLM transport/parse failure) gets a bounded replan pass —
    same inner cap as a geometry defect — never an immediate fail."""
    assert cap_for_stage("verifier_error") == INNER_CAP == 5
    assert not is_exhausted("verifier_error", 4)
    assert is_exhausted("verifier_error", 5)


def test_outer_stage_cap_is_three():
    assert cap_for_stage("visual_mismatch") == OUTER_CAP == 3


def test_is_exhausted_at_cap():
    assert not is_exhausted("cadquery_compile", 4)
    assert is_exhausted("cadquery_compile", 5)
    assert not is_exhausted("visual_mismatch", 2)
    assert is_exhausted("visual_mismatch", 3)


def test_every_stage_has_a_skill():
    for stage in ("cadquery_compile", "mesh_repair", "visual_mismatch", "primitive_gap"):
        assert stage in STAGE_TO_SKILL


def test_feedback_message_names_stage_and_skill_and_plan():
    msg = build_feedback_message("visual_mismatch", "too tall", _CUBE)
    assert "visual_mismatch" in msg
    assert "refinement_guidance" in msg
    assert "too tall" in msg
    assert "box" in msg  # the prior plan is embedded


def test_feedback_message_notes_verifier_error_is_not_a_plan_defect():
    msg = build_feedback_message(
        "verifier_error", "[verifier-error] VLM judge failed: unterminated JSON object", _CUBE
    )
    assert "verifier_error" in msg
    assert "NOT a" in msg  # the caveat: this stage doesn't mean the plan is wrong


def test_collect_feedback_detail_prefers_verifier_feedback_for_visual():
    assert collect_feedback_detail("visual_mismatch", {"feedback": "wrong shape"}) == "wrong shape"


def test_collect_feedback_detail_uses_error_for_other_stages():
    assert collect_feedback_detail("cadquery_compile", {"error": "boom"}) == "boom"


def test_replan_appends_system_feedback_and_calls_planner():
    captured = {}

    def fake_planner(prompt, history):
        captured["prompt"] = prompt
        captured["history"] = history
        return _CUBE

    out = replan_with_feedback(
        original_prompt="make a cube",
        last_plan=_CUBE,
        failure_stage="cadquery_compile",
        detail="syntax error",
        prior_history=[{"role": "user", "content": "hi"}],
        planner_fn=fake_planner,
    )
    assert out is _CUBE
    assert captured["prompt"] == "make a cube"
    # original history preserved + a system feedback turn appended
    assert captured["history"][0] == {"role": "user", "content": "hi"}
    assert captured["history"][-1]["role"] == "system"
    assert "cadquery_compile" in captured["history"][-1]["content"]


def test_replan_propagates_planner_exception():
    """No ask_user fallback — a planner_fn failure must raise, not be swallowed."""
    import pytest

    def failing_planner(prompt, history):
        raise RuntimeError("RLM budget exhausted")

    with pytest.raises(RuntimeError, match="budget exhausted"):
        replan_with_feedback(
            original_prompt="make a cube",
            last_plan=_CUBE,
            failure_stage="cadquery_compile",
            detail="syntax error",
            prior_history=[],
            planner_fn=failing_planner,
        )


def test_replan_call_retries_twice_before_raising():
    """A flaky replan call gets REPLAN_CALL_RETRIES (2) attempts before it counts
    as a failure — distinct from the stage's outer attempt cap."""
    import pytest

    from runtime.replan import REPLAN_CALL_RETRIES

    calls = {"n": 0}

    def always_failing_planner(prompt, history):
        calls["n"] += 1
        raise RuntimeError(f"attempt {calls['n']} failed")

    assert REPLAN_CALL_RETRIES == 2
    with pytest.raises(RuntimeError, match="attempt 2 failed"):
        replan_with_feedback(
            original_prompt="make a cube",
            last_plan=_CUBE,
            failure_stage="cadquery_compile",
            detail="syntax error",
            prior_history=[],
            planner_fn=always_failing_planner,
        )
    assert calls["n"] == 2  # tried exactly REPLAN_CALL_RETRIES times, no more


def test_replan_call_succeeds_on_second_attempt():
    """First call flakes, second succeeds — the transient failure is swallowed."""
    calls = {"n": 0}

    def flaky_then_ok_planner(prompt, history):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient LLM hiccup")
        return _CUBE

    out = replan_with_feedback(
        original_prompt="make a cube",
        last_plan=_CUBE,
        failure_stage="cadquery_compile",
        detail="syntax error",
        prior_history=[],
        planner_fn=flaky_then_ok_planner,
    )
    assert out is _CUBE
    assert calls["n"] == 2


# ── edit replan (post-design edit requests, not failures) ───────────────────


def test_build_edit_message_is_not_failure_framed():
    msg = build_edit_message("make it 20mm taller", _CUBE)
    assert "make it 20mm taller" in msg
    assert "box" in msg  # the current plan is embedded
    assert "not a failure" in msg.lower()
    assert "failed at stage" not in msg  # distinct wording from build_feedback_message


def test_replan_for_edit_calls_planner_with_edit_message():
    captured = {}

    def fake_planner(prompt, history):
        captured["prompt"] = prompt
        captured["history"] = history
        return _CUBE

    out = replan_for_edit(
        original_prompt="a cube",
        last_plan=_CUBE,
        edit_text="add a hole in the top",
        prior_history=[{"role": "user", "content": "established facts"}],
        planner_fn=fake_planner,
    )
    assert out is _CUBE
    assert captured["history"][0] == {"role": "user", "content": "established facts"}
    assert "add a hole in the top" in captured["history"][-1]["content"]


def test_replan_for_edit_does_not_touch_stage_caps():
    """An edit is fresh user intent, not a bounded retry — cap_for_stage/
    is_exhausted are stage-keyed and untouched by anything edit-related."""
    assert cap_for_stage("cadquery_compile") == INNER_CAP
    assert cap_for_stage("visual_mismatch") == OUTER_CAP


def test_replan_for_edit_retries_on_flaky_call_then_raises():
    calls = {"n": 0}

    def always_failing(prompt, history):
        calls["n"] += 1
        raise RuntimeError(f"attempt {calls['n']}")

    import pytest

    with pytest.raises(RuntimeError, match="attempt 2"):
        replan_for_edit(
            original_prompt="a cube",
            last_plan=_CUBE,
            edit_text="make it bigger",
            prior_history=[],
            planner_fn=always_failing,
        )
    assert calls["n"] == 2
