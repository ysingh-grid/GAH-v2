"""Real-world integration tests for the geometry loop.

These tests run the actual compile -> CadQuery -> MeshLib -> render -> trace
path. The VLM judge is patched with deterministic verdicts unless a separate
live model test is explicitly requested.
"""

import shutil
from unittest.mock import patch

import pytest

from runtime import schema
from runtime.loop import run_geometry_loop
from runtime.schema import plan_from_dict
from tests.real_world_scenarios import mounting_plate_with_four_holes

pytest.importorskip("cadquery")
pytest.importorskip("meshlib.mrmeshpy")

LIBRARY = schema.load_library()

_MOUNTING_PLATE = mounting_plate_with_four_holes().plan

# Structurally valid but uses a primitive the library can't express -> primitive_gap.
_AEROFOIL = plan_from_dict(
    {
        "part_name": "blade",
        "steps": [{"id": "b", "primitive": "aerofoil", "operation": "base"}],
    }
)


def _planner_returning(*outputs):
    """A fake planner that yields the given PrimitivePlans in order, then repeats last."""
    calls = {"n": 0}

    def fake(prompt, history):
        i = min(calls["n"], len(outputs) - 1)
        calls["n"] += 1
        return outputs[i]

    fake.calls = calls
    return fake


def _cleanup(run_id):
    from tools.artifacts import run_dir

    shutil.rmtree(run_dir(run_id), ignore_errors=True)


def test_loop_success_on_mounting_plate_with_mock_vlm_judge():
    from tools.artifacts import new_run_id

    scenario = mounting_plate_with_four_holes()
    run_id = new_run_id("test_loop_mounting_plate")
    planner = _planner_returning(scenario.plan)
    try:
        with patch("tools.verify_geometry.verify_geometry") as judge:
            judge.return_value = {
                "passed": True,
                "feedback": "All constraints met.",
                "render_png": "",
            }
            result = run_geometry_loop(
                original_prompt=scenario.prompt,
                initial_plan=scenario.plan,
                planner_fn=planner,
                library=LIBRARY,
                run_id=run_id,
                verify=True,
            )
        assert result.status == "success"
        assert result.failure_category is None
        assert result.attempts == 1
        assert planner.calls["n"] == 0  # never needed to replan
        assert result.trace_path.endswith("trace.json")
        judge.assert_called_once()
    finally:
        _cleanup(run_id)


def test_loop_replans_primitive_gap_then_succeeds():
    from tools.artifacts import new_run_id

    run_id = new_run_id("test_loop_replan")
    planner = _planner_returning(_MOUNTING_PLATE)
    try:
        result = run_geometry_loop(
            original_prompt="a blade, else a practical mounting plate",
            initial_plan=_AEROFOIL,  # fails primitive_gap on attempt 1
            planner_fn=planner,
            library=LIBRARY,
            run_id=run_id,
            verify=False,
        )
        assert result.status == "success"
        assert planner.calls["n"] == 1  # replanned exactly once
        assert result.final_plan["part_name"] == "electronics_mounting_plate"
    finally:
        _cleanup(run_id)


def test_loop_exhausts_inner_cap_and_fails_with_category():
    from tools.artifacts import new_run_id

    run_id = new_run_id("test_loop_exhaust")
    # planner keeps returning the unbuildable plan -> never fixes it
    planner = _planner_returning(_AEROFOIL)
    try:
        result = run_geometry_loop(
            original_prompt="an impossible blade",
            initial_plan=_AEROFOIL,
            planner_fn=planner,
            library=LIBRARY,
            run_id=run_id,
            verify=False,
        )
        assert result.status == "failed"
        assert result.failure_category == "primitive_gap"
        assert "exhausted" in result.message
    finally:
        _cleanup(run_id)


def test_loop_replans_when_vlm_rejects_visual_result():
    from tools.artifacts import new_run_id

    scenario = mounting_plate_with_four_holes()
    run_id = new_run_id("test_loop_vlm_replan")
    planner = _planner_returning(scenario.plan)
    try:
        with patch("tools.verify_geometry.verify_geometry") as judge:
            judge.side_effect = [
                {
                    "passed": False,
                    "feedback": "Only two holes are visible; add the rear pair.",
                    "render_png": "",
                },
                {
                    "passed": True,
                    "feedback": "All constraints met.",
                    "render_png": "",
                },
            ]
            result = run_geometry_loop(
                original_prompt=scenario.prompt,
                initial_plan=scenario.plan,
                planner_fn=planner,
                library=LIBRARY,
                run_id=run_id,
                verify=True,
            )
        assert result.status == "success"
        assert result.attempts == 2
        assert planner.calls["n"] == 1
        assert judge.call_count == 2
    finally:
        _cleanup(run_id)


def test_loop_replans_on_verifier_error_instead_of_failing_immediately():
    """verifier_error (VLM transport/parse failure) gets a bounded replan pass,
    same as any other stage — no fail-fast special case."""
    from tools.artifacts import new_run_id

    scenario = mounting_plate_with_four_holes()
    run_id = new_run_id("test_loop_verifier_error_replan")
    planner = _planner_returning(scenario.plan)
    try:
        with patch("tools.verify_geometry.verify_geometry") as judge:
            judge.side_effect = [
                {
                    "passed": False,
                    "failure_stage": "verifier_error",
                    "feedback": "[verifier-error] VLM judge failed: unterminated JSON object",
                    "render_png": "",
                },
                {
                    "passed": True,
                    "feedback": "All constraints met.",
                    "render_png": "",
                },
            ]
            result = run_geometry_loop(
                original_prompt=scenario.prompt,
                initial_plan=scenario.plan,
                planner_fn=planner,
                library=LIBRARY,
                run_id=run_id,
                verify=True,
            )
        assert result.status == "success"  # NOT an immediate "failed"
        assert planner.calls["n"] == 1  # replan was actually attempted
        assert judge.call_count == 2
    finally:
        _cleanup(run_id)


def test_loop_fails_when_replanner_raises():
    """No ask_user escalation — a replanner failure is a categorized 'failed' result."""
    from tools.artifacts import new_run_id

    run_id = new_run_id("test_loop_replan_error")

    def failing_planner(prompt, history):
        raise RuntimeError("RLM budget exhausted")

    try:
        result = run_geometry_loop(
            original_prompt="a blade",
            initial_plan=_AEROFOIL,
            planner_fn=failing_planner,
            library=LIBRARY,
            run_id=run_id,
            verify=False,
        )
        assert result.status == "failed"
        assert "replanner failed" in result.message
        assert result.failure_category == "geometry_invalidity"
    finally:
        _cleanup(run_id)
