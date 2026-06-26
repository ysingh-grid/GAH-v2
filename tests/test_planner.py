"""Tests for runtime/planner.py — typed output contract + pure helpers.

The live RLM turn is gated behind RUN_RLM_LIVE (needs deno + network + spend).
"""

import os

import pytest
from pydantic import ValidationError

from runtime.planner import (
    PlannerOutput,
    build_planner_query,
    parse_planner_result,
    run_planner_turn,
)

_CUBE_PLAN = {
    "part_name": "cube",
    "steps": [
        {
            "id": "body",
            "primitive": "box",
            "operation": "base",
            "parameters": {"length": 60.0, "width": 60.0, "height": 60.0},
        }
    ],
}


# ── output contract ──────────────────────────────────────────────────────────


def test_ask_user_output_is_valid():
    out = PlannerOutput.model_validate(
        {
            "action": "ask_user",
            "question": "What wall thickness do you want?",
            "suggested_options": ["1.5 mm", "2 mm", "3 mm"],
        }
    )
    assert out.action == "ask_user"
    assert out.plan is None


def test_ask_user_without_question_raises():
    with pytest.raises(ValidationError, match="requires a non-empty 'question'"):
        PlannerOutput.model_validate({"action": "ask_user"})


def test_plan_ready_output_carries_validated_plan():
    out = parse_planner_result({"action": "plan_ready", "plan": _CUBE_PLAN})
    assert out.action == "plan_ready"
    assert out.plan is not None
    assert out.plan.part_name == "cube"
    assert out.plan.steps[0].primitive == "box"


def test_plan_ready_without_plan_raises():
    with pytest.raises(ValidationError, match="requires a 'plan'"):
        PlannerOutput.model_validate({"action": "plan_ready"})


def test_plan_ready_with_structurally_invalid_plan_raises():
    bad = {"action": "plan_ready", "plan": {"part_name": "x", "steps": []}}
    with pytest.raises(ValidationError):
        PlannerOutput.model_validate(bad)


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        PlannerOutput.model_validate({"action": "ask_user", "question": "q", "bogus": 1})


# ── query assembly ───────────────────────────────────────────────────────────


def test_build_planner_query_shape():
    q = build_planner_query("make a 60mm cube", [{"role": "user", "content": "hi"}])
    assert q["original_prompt"] == "make a 60mm cube"
    assert q["chat_history"][0]["content"] == "hi"
    assert q["task"] == "make a 60mm cube"


# ── live turn (opt-in) ───────────────────────────────────────────────────────


@pytest.mark.skipif(
    not os.getenv("RUN_RLM_LIVE"), reason="set RUN_RLM_LIVE=1 to run a real RLM turn"
)
def test_live_planner_turn_returns_typed_output():
    backend_url = os.getenv("DTCM_BACKEND_URL", "http://127.0.0.1:8001")
    out = run_planner_turn(
        "Design a 60mm x 60mm x 60mm solid cube.",
        chat_history=[],
        backend_url=backend_url,
    )
    assert out.action in ("ask_user", "plan_ready")
