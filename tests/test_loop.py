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

    def fake(prompt, history, current_plan=None):
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

    def failing_planner(prompt, history, current_plan=None):
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


def test_loop_threads_prior_failures_into_replan_history():
    """Each replan round must see STATE from earlier rounds — the plan that
    failed AND the failure it hit — on top of the pre-planner intake base.
    Previously history never accumulated, so every replan was stateless and
    could retry a fix an earlier round had already tried."""
    from tools.artifacts import new_run_id

    scenario = mounting_plate_with_four_holes()
    run_id = new_run_id("test_loop_replan_history")
    seen_histories: list[list[dict]] = []

    def recording_planner(prompt, history, current_plan=None):
        seen_histories.append(list(history))
        return scenario.plan

    intake_base = [
        {"role": "user", "content": "Established design facts from intake:\n- plate 100x60mm"}
    ]
    try:
        with patch("tools.verify_geometry.verify_geometry") as judge:
            judge.side_effect = [
                {"passed": False, "feedback": "holes missing", "render_png": ""},
                {"passed": False, "feedback": "holes still missing", "render_png": ""},
                {"passed": True, "feedback": "All constraints met.", "render_png": ""},
            ]
            result = run_geometry_loop(
                original_prompt=scenario.prompt,
                initial_plan=scenario.plan,
                planner_fn=recording_planner,
                library=LIBRARY,
                run_id=run_id,
                verify=True,
                history=intake_base,
            )
        assert result.status == "success"
        assert len(seen_histories) == 2
        # Both replans: the intake-facts base leads the history (never raw chat).
        assert seen_histories[0][0]["content"].startswith("Established design facts")
        assert seen_histories[1][0]["content"].startswith("Established design facts")
        # 1st replan: no prior attempts yet — base + current feedback message only.
        assert not any("[attempt" in m["content"] for m in seen_histories[0])
        # 2nd replan: carries the 1st round's failed PLAN and its failure.
        plan_records = [
            m for m in seen_histories[1]
            if m["role"] == "planner" and "plan]" in m["content"]
        ]
        result_records = [
            m for m in seen_histories[1]
            if m["role"] == "system" and "result]" in m["content"]
        ]
        assert len(plan_records) == 1
        assert '"primitive":"box"' in plan_records[0]["content"]  # failed plan JSON present
        assert len(result_records) == 1
        assert "visual_mismatch" in result_records[0]["content"]
        assert "holes missing" in result_records[0]["content"]
    finally:
        _cleanup(run_id)


def test_loop_skips_regenerate_when_replan_returns_plan_unchanged():
    """verifier_error + unchanged plan -> the geometry on disk is identical, so
    the loop must NOT re-run compile/execute/inspect/render — straight to re-verify."""
    import runtime.loop as loop_mod
    from tools.artifacts import new_run_id

    scenario = mounting_plate_with_four_holes()
    run_id = new_run_id("test_loop_reuse_geometry")
    planner = _planner_returning(scenario.plan)  # returns the SAME plan (unchanged)

    real_run_geometry = loop_mod._run_geometry
    geometry_calls = {"n": 0}

    def counting_run_geometry(*args, **kwargs):
        geometry_calls["n"] += 1
        return real_run_geometry(*args, **kwargs)

    try:
        with (
            patch("runtime.loop._run_geometry", side_effect=counting_run_geometry),
            patch("tools.verify_geometry.verify_geometry") as judge,
        ):
            judge.side_effect = [
                {
                    "passed": False,
                    "failure_stage": "verifier_error",
                    "feedback": "[verifier-error] VLM judge failed: unterminated JSON object",
                    "render_png": "",
                },
                {"passed": True, "feedback": "All constraints met.", "render_png": ""},
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
        assert judge.call_count == 2       # verify DID run again
        assert geometry_calls["n"] == 1    # geometry was NOT regenerated
    finally:
        _cleanup(run_id)
