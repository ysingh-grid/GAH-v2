"""Unit tests for runtime/replan.py — caps, stage->skill, feedback, re-entry."""

from runtime.planner import PlannerOutput
from runtime.replan import (
    INNER_CAP,
    OUTER_CAP,
    STAGE_TO_SKILL,
    build_feedback_message,
    cap_for_stage,
    collect_feedback_detail,
    is_exhausted,
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


def test_outer_stage_cap_is_two():
    assert cap_for_stage("visual_mismatch") == OUTER_CAP == 2


def test_is_exhausted_at_cap():
    assert not is_exhausted("cadquery_compile", 4)
    assert is_exhausted("cadquery_compile", 5)
    assert not is_exhausted("visual_mismatch", 1)
    assert is_exhausted("visual_mismatch", 2)


def test_every_stage_has_a_skill():
    for stage in ("cadquery_compile", "mesh_repair", "visual_mismatch", "primitive_gap"):
        assert stage in STAGE_TO_SKILL


def test_feedback_message_names_stage_and_skill_and_plan():
    msg = build_feedback_message("visual_mismatch", "too tall", _CUBE)
    assert "visual_mismatch" in msg
    assert "refinement_guidance" in msg
    assert "too tall" in msg
    assert "box" in msg  # the prior plan is embedded


def test_collect_feedback_detail_prefers_verifier_feedback_for_visual():
    assert collect_feedback_detail("visual_mismatch", {"feedback": "wrong shape"}) == "wrong shape"


def test_collect_feedback_detail_uses_error_for_other_stages():
    assert collect_feedback_detail("cadquery_compile", {"error": "boom"}) == "boom"


def test_replan_appends_system_feedback_and_calls_planner():
    captured = {}

    def fake_planner(prompt, history):
        captured["prompt"] = prompt
        captured["history"] = history
        return PlannerOutput(action="plan_ready", plan=_CUBE)

    out = replan_with_feedback(
        original_prompt="make a cube",
        last_plan=_CUBE,
        failure_stage="cadquery_compile",
        detail="syntax error",
        prior_history=[{"role": "user", "content": "hi"}],
        planner_fn=fake_planner,
    )
    assert out.action == "plan_ready"
    assert captured["prompt"] == "make a cube"
    # original history preserved + a system feedback turn appended
    assert captured["history"][0] == {"role": "user", "content": "hi"}
    assert captured["history"][-1]["role"] == "system"
    assert "cadquery_compile" in captured["history"][-1]["content"]
