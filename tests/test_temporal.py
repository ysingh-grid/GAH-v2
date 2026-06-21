"""Tests for the Temporal workflow layer (M11).

Uses WorkflowEnvironment.start_local() for in-process Temporal testing —
no external Temporal server required.  Activities are mocked so the tests
are deterministic and don't touch the real geometry/CadQuery stack.

Run:
    uv run pytest tests/test_temporal.py -v
"""

from __future__ import annotations

import concurrent.futures
from unittest.mock import MagicMock, patch

import pytest

from temporal.shared import DesignInput, DesignResult
from temporal.workflow import DesignWorkflow

# ── Helpers ───────────────────────────────────────────────────────────────────

_SAMPLE_INPUT = DesignInput(
    original_prompt="make a cube",
    plan_dict={"steps": []},
    run_id="test-run-001",
    backend_url="http://localhost:8001",
)

_SUCCESS_GEO = DesignResult(
    status="success",
    final_plan={"steps": [{"primitive": "box"}]},
    run_id="test-run-001",
)

_FAILED_GEO = DesignResult(
    status="failed",
    failure_category="geometry_error",
    message="mesh failed",
    run_id="test-run-001",
)

_NEEDS_USER_GEO = DesignResult(
    status="needs_user",
    question="What material?",
    run_id="test-run-001",
)

_FORGE_JS_OUTPUT = "const part = new Box(1,1,1);"


# ── Unit tests: shared dataclasses ────────────────────────────────────────────

class TestDesignInput:
    def test_defaults(self):
        inp = DesignInput(
            original_prompt="sphere",
            plan_dict={},
            run_id="r1",
        )
        assert inp.backend_url == "http://localhost:8001"

    def test_fields(self):
        inp = DesignInput(
            original_prompt="cube",
            plan_dict={"steps": [1, 2]},
            run_id="r2",
            backend_url="http://test:9999",
        )
        assert inp.original_prompt == "cube"
        assert inp.plan_dict == {"steps": [1, 2]}
        assert inp.run_id == "r2"
        assert inp.backend_url == "http://test:9999"


class TestDesignResult:
    def test_success_defaults(self):
        r = DesignResult(status="success")
        assert r.forge_js == ""
        assert r.final_plan == {}
        assert r.run_id == ""
        assert r.failure_category == ""
        assert r.message == ""
        assert r.question == ""

    def test_failed_fields(self):
        r = DesignResult(
            status="failed",
            failure_category="geometry_error",
            message="cadquery blew up",
            run_id="r3",
        )
        assert r.status == "failed"
        assert r.failure_category == "geometry_error"
        assert r.message == "cadquery blew up"

    def test_needs_user_fields(self):
        r = DesignResult(status="needs_user", question="What radius?")
        assert r.status == "needs_user"
        assert r.question == "What radius?"

    def test_success_with_forge_js(self):
        r = DesignResult(
            status="success",
            forge_js="const p = new Box(1,1,1);",
            final_plan={"steps": []},
            run_id="r4",
        )
        assert r.forge_js == "const p = new Box(1,1,1);"

    def test_final_plan_is_independent_dict(self):
        r1 = DesignResult(status="success")
        r2 = DesignResult(status="success")
        r1.final_plan["x"] = 1
        assert "x" not in r2.final_plan


# ── Workflow tests: in-process Temporal ───────────────────────────────────────

@pytest.mark.anyio
async def test_workflow_success_path():
    """Geometry succeeds → compile runs → DesignResult with forge_js returned."""
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    from temporal.activities import compile_forge_activity, run_geometry_activity

    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(
            env.client,
            task_queue="test-design",
            workflows=[DesignWorkflow],
            activities=[run_geometry_activity, compile_forge_activity],
            activity_executor=concurrent.futures.ThreadPoolExecutor(max_workers=2),
        ):
            # Mock both activity implementations
            with (
                patch(
                    "temporal.activities.run_geometry_loop",
                    return_value=MagicMock(
                        status="success",
                        final_plan={"steps": [{"primitive": "box"}]},
                        failure_category=None,
                        message=None,
                        question=None,
                    ),
                ),
                patch("temporal.activities.load_library", return_value={}),
                patch(
                    "temporal.activities.compile_plan_to_forge",
                    return_value=_FORGE_JS_OUTPUT,
                ),
                patch(
                    "temporal.activities.PrimitivePlan.model_validate",
                    return_value=MagicMock(),
                ),
            ):
                result: DesignResult = await env.client.execute_workflow(
                    DesignWorkflow.run,
                    _SAMPLE_INPUT,
                    id="wf-success-001",
                    task_queue="test-design",
                )

    assert result.status == "success"
    assert result.forge_js == _FORGE_JS_OUTPUT
    assert result.final_plan == {"steps": [{"primitive": "box"}]}


@pytest.mark.anyio
async def test_workflow_geometry_failed_short_circuits():
    """Geometry fails → workflow returns failed result immediately (no compile)."""
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    from temporal.activities import compile_forge_activity, run_geometry_activity

    compile_called = []

    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(
            env.client,
            task_queue="test-design",
            workflows=[DesignWorkflow],
            activities=[run_geometry_activity, compile_forge_activity],
            activity_executor=concurrent.futures.ThreadPoolExecutor(max_workers=2),
        ):
            with (
                patch(
                    "temporal.activities.run_geometry_loop",
                    return_value=MagicMock(
                        status="failed",
                        final_plan=None,
                        failure_category="geometry_error",
                        message="mesh failed",
                        question=None,
                    ),
                ),
                patch("temporal.activities.load_library", return_value={}),
                patch(
                    "temporal.activities.compile_plan_to_forge",
                    side_effect=lambda *a, **kw: compile_called.append(1) or "",
                ),
                patch(
                    "temporal.activities.PrimitivePlan.model_validate",
                    return_value=MagicMock(),
                ),
            ):
                result: DesignResult = await env.client.execute_workflow(
                    DesignWorkflow.run,
                    _SAMPLE_INPUT,
                    id="wf-failed-001",
                    task_queue="test-design",
                )

    assert result.status == "failed"
    assert result.failure_category == "geometry_error"
    assert compile_called == [], "compile_forge_activity must NOT be called when geometry fails"


@pytest.mark.anyio
async def test_workflow_needs_user_short_circuits():
    """Geometry needs_user → workflow returns needs_user (no compile)."""
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    from temporal.activities import compile_forge_activity, run_geometry_activity

    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(
            env.client,
            task_queue="test-design",
            workflows=[DesignWorkflow],
            activities=[run_geometry_activity, compile_forge_activity],
            activity_executor=concurrent.futures.ThreadPoolExecutor(max_workers=2),
        ):
            with (
                patch(
                    "temporal.activities.run_geometry_loop",
                    return_value=MagicMock(
                        status="needs_user",
                        final_plan=None,
                        failure_category=None,
                        message=None,
                        question="What material?",
                    ),
                ),
                patch("temporal.activities.load_library", return_value={}),
                patch(
                    "temporal.activities.PrimitivePlan.model_validate",
                    return_value=MagicMock(),
                ),
            ):
                result: DesignResult = await env.client.execute_workflow(
                    DesignWorkflow.run,
                    _SAMPLE_INPUT,
                    id="wf-needs-001",
                    task_queue="test-design",
                )

    assert result.status == "needs_user"
    assert result.question == "What material?"


@pytest.mark.anyio
async def test_workflow_compile_failure_returns_empty_forge_js():
    """compile_forge_activity exception → activity returns '' → result still success."""
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    from temporal.activities import compile_forge_activity, run_geometry_activity

    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(
            env.client,
            task_queue="test-design",
            workflows=[DesignWorkflow],
            activities=[run_geometry_activity, compile_forge_activity],
            activity_executor=concurrent.futures.ThreadPoolExecutor(max_workers=2),
        ):
            with (
                patch(
                    "temporal.activities.run_geometry_loop",
                    return_value=MagicMock(
                        status="success",
                        final_plan={"steps": []},
                        failure_category=None,
                        message=None,
                        question=None,
                    ),
                ),
                patch("temporal.activities.load_library", return_value={}),
                patch(
                    "temporal.activities.compile_plan_to_forge",
                    side_effect=RuntimeError("forge compile boom"),
                ),
                patch(
                    "temporal.activities.PrimitivePlan.model_validate",
                    return_value=MagicMock(),
                ),
            ):
                result: DesignResult = await env.client.execute_workflow(
                    DesignWorkflow.run,
                    _SAMPLE_INPUT,
                    id="wf-compile-fail-001",
                    task_queue="test-design",
                )

    # compile exception → activity swallows it and returns "" → workflow still success
    assert result.status == "success"
    assert result.forge_js == ""


# ── docker-compose temporal services ─────────────────────────────────────────

class TestDockerComposeTemporal:
    """YAML structure tests for the Temporal additions in docker-compose.yml."""

    @pytest.fixture(scope="class")
    @classmethod
    def compose(cls):
        import yaml
        with open("docker-compose.yml") as f:
            return yaml.safe_load(f)

    def test_temporal_service_exists(self, compose):
        assert "temporal" in compose["services"]

    def test_temporal_image(self, compose):
        img = compose["services"]["temporal"]["image"]
        assert "temporalio" in img

    def test_temporal_grpc_port(self, compose):
        ports = compose["services"]["temporal"]["ports"]
        port_strings = [str(p) for p in ports]
        assert any("7233" in p for p in port_strings)

    def test_temporal_web_ui_port(self, compose):
        ports = compose["services"]["temporal"]["ports"]
        port_strings = [str(p) for p in ports]
        assert any("8088" in p for p in port_strings)

    def test_temporal_profile(self, compose):
        profiles = compose["services"]["temporal"].get("profiles", [])
        assert "temporal" in profiles

    def test_worker_service_exists(self, compose):
        assert "worker" in compose["services"]

    def test_worker_command(self, compose):
        cmd = compose["services"]["worker"]["command"]
        assert "temporal.worker" in " ".join(str(c) for c in cmd)

    def test_worker_depends_on_temporal(self, compose):
        deps = compose["services"]["worker"].get("depends_on", {})
        assert "temporal" in deps

    def test_worker_profile(self, compose):
        profiles = compose["services"]["worker"].get("profiles", [])
        assert "temporal" in profiles

    def test_worker_temporal_host_env(self, compose):
        env = compose["services"]["worker"].get("environment", {})
        assert "TEMPORAL_HOST" in env

    def test_temporal_data_volume_declared(self, compose):
        volumes = compose.get("volumes", {})
        assert "temporal-data" in volumes

    def test_backend_temporal_host_env(self, compose):
        """Backend must have TEMPORAL_HOST (even if empty) so gating works."""
        env = compose["services"]["backend"].get("environment", {})
        assert "TEMPORAL_HOST" in env


# ── runner.py integration: _USE_TEMPORAL flag ────────────────────────────────

class TestRunnerTemporalFlag:
    def test_flag_false_without_env(self, monkeypatch):
        monkeypatch.delenv("TEMPORAL_HOST", raising=False)
        import importlib

        import backend.designs.runner as runner_mod
        importlib.reload(runner_mod)
        assert runner_mod._USE_TEMPORAL is False

    def test_flag_true_with_env(self, monkeypatch):
        monkeypatch.setenv("TEMPORAL_HOST", "localhost:7233")
        import importlib

        import backend.designs.runner as runner_mod
        importlib.reload(runner_mod)
        assert runner_mod._USE_TEMPORAL is True

    def test_flag_false_empty_string(self, monkeypatch):
        monkeypatch.setenv("TEMPORAL_HOST", "")
        import importlib

        import backend.designs.runner as runner_mod
        importlib.reload(runner_mod)
        assert runner_mod._USE_TEMPORAL is False
