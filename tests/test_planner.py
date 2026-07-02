"""Tests for runtime/planner.py — typed output contract + pure helpers.

The live RLM turn is gated behind RUN_RLM_LIVE (needs deno + network + spend).
"""

import os

import pytest
from pydantic import ValidationError

from runtime.planner import (
    build_planner_query,
    parse_planner_result,
    run_planner_turn,
)
from runtime.schema import PrimitivePlan

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


def test_plan_result_carries_validated_plan():
    out = parse_planner_result(_CUBE_PLAN)
    assert out.part_name == "cube"
    assert out.steps[0].primitive == "box"


def test_parse_planner_result_accepts_already_validated_model():
    expected = PrimitivePlan.model_validate(_CUBE_PLAN)
    assert parse_planner_result(expected) is expected


def test_plan_with_no_steps_raises():
    with pytest.raises(ValidationError):
        parse_planner_result({"part_name": "x", "steps": []})


def test_plan_with_two_base_steps_raises():
    bad = {
        "part_name": "x",
        "steps": [
            {"id": "a", "primitive": "box", "operation": "base"},
            {"id": "b", "primitive": "box", "operation": "base"},
        ],
    }
    with pytest.raises(ValidationError, match="exactly one 'base'"):
        parse_planner_result(bad)


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        parse_planner_result({**_CUBE_PLAN, "bogus": 1})


# ── query assembly ───────────────────────────────────────────────────────────


def test_build_planner_query_shape():
    q = build_planner_query("make a 60mm cube", [{"role": "user", "content": "hi"}])
    assert q["original_prompt"] == "make a 60mm cube"
    assert q["chat_history"][0]["content"] == "hi"
    assert q["task"] == "make a 60mm cube"


def test_run_planner_turn_uses_typed_output_schema(monkeypatch):
    import fast_rlm

    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return {"results": _CUBE_PLAN}

    monkeypatch.setattr(fast_rlm, "run", fake_run)
    monkeypatch.setattr("runtime.planner.list_primitives", lambda: ["box"])
    monkeypatch.setattr("runtime.planner.list_kb_index", lambda: {})

    out = run_planner_turn(
        "make a 60mm cube",
        [{"role": "user", "content": "make a 60mm cube"}],
        backend_url="http://backend.test",
        config={},
    )

    assert out.part_name == "cube"
    assert captured["output_schema"] is PrimitivePlan
    assert captured["env_variables"]["DTCM_BACKEND_URL"] == "http://backend.test"


def test_run_planner_turn_propagates_exception(monkeypatch):
    """No ask_user fallback — an unrecoverable RLM failure must raise, not be masked."""
    import fast_rlm

    def fake_run(*args, **kwargs):
        raise RuntimeError("budget exhausted")

    monkeypatch.setattr(fast_rlm, "run", fake_run)
    monkeypatch.setattr("runtime.planner.list_primitives", lambda: ["box"])
    monkeypatch.setattr("runtime.planner.list_kb_index", lambda: {})

    with pytest.raises(RuntimeError, match="budget exhausted"):
        run_planner_turn(
            "make a 60mm cube", [], backend_url="http://backend.test", config={}
        )


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
    assert out.part_name
