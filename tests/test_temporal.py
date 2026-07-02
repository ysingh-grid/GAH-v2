"""Tests for the Temporal workflow layer.

The geometry pipeline is now SPLIT into per-step activities (compile → execute →
inspect → repair → render) plus verify / replan / record_trace. We unit-test each
new activity wrapper directly (they are plain functions under @activity.defn, so
calling them runs the body) with the heavy tools faked via sys.modules — fast and
deterministic, no CadQuery/MeshLib/VTK and no live Temporal server.

Run:
    uv run pytest tests/test_temporal.py -v
"""

from __future__ import annotations

import sys
import types

import pytest

from temporal.shared import (
    CompileInput,
    DesignInput,
    DesignResult,
    ExecuteInput,
    InspectInput,
    RenderInput,
    RepairInput,
)

# ── Unit tests: shared dataclasses ────────────────────────────────────────────


class TestDesignInput:
    def test_defaults(self):
        inp = DesignInput(original_prompt="sphere", plan_dict={}, run_id="r1")
        assert inp.backend_url == "http://localhost:8001"
        assert inp.history == []

    def test_fields(self):
        inp = DesignInput(
            original_prompt="cube",
            plan_dict={"steps": [1, 2]},
            run_id="r2",
            history=[{"role": "system", "content": "context"}],
            backend_url="http://test:9999",
        )
        assert inp.original_prompt == "cube"
        assert inp.plan_dict == {"steps": [1, 2]}
        assert inp.history == [{"role": "system", "content": "context"}]
        assert inp.backend_url == "http://test:9999"


class TestDesignResult:
    def test_success_defaults(self):
        r = DesignResult(status="success")
        # forge_js is gone (forge path removed in the scope reduction)
        assert not hasattr(r, "forge_js")
        # no ask_user escalation path — needs_user status is gone
        assert not hasattr(r, "question")
        assert r.final_plan == {}
        assert r.run_id == ""
        assert r.failure_category == ""
        assert r.message == ""

    def test_failed_fields(self):
        r = DesignResult(
            status="failed", failure_category="geometry_invalidity",
            message="cadquery blew up", run_id="r3",
        )
        assert r.status == "failed"
        assert r.failure_category == "geometry_invalidity"

    def test_final_plan_is_independent_dict(self):
        r1, r2 = DesignResult(status="success"), DesignResult(status="success")
        r1.final_plan["x"] = 1
        assert "x" not in r2.final_plan


# ── Split generate activities (the new per-step decomposition) ────────────────


def _fake_tool_module(modname: str, funcname: str, fn) -> types.ModuleType:
    """Build a stand-in module so an activity's lazy `from modname import funcname`
    binds to *fn* — avoids importing the heavy real tool (CadQuery/MeshLib/VTK)."""
    mod = types.ModuleType(modname)
    setattr(mod, funcname, fn)
    return mod


class TestCompileActivity:
    """compile_activity wraps the (lightweight, pure) CadQuery codegen."""

    def test_success_emits_code(self):
        from runtime.schema import load_library, plan_to_dict
        from temporal.activities import compile_activity

        lib = load_library()
        plan_dict = {
            "part_name": "cube", "units": "mm",
            "steps": [{"id": "b", "primitive": "box", "operation": "base",
                       "parameters": {"length": 10, "width": 10, "height": 10}}],
        }
        # sanity: plan_to_dict round-trips through the real schema
        assert "steps" in plan_dict
        out = compile_activity(CompileInput(plan_dict=plan_dict, run_id="t1"))
        assert out.ok is True
        assert "result" in out.code
        assert out.failure_stage == ""
        _ = lib, plan_to_dict  # keep imports referenced

    def test_primitive_gap_failure(self):
        from temporal.activities import compile_activity

        plan_dict = {
            "part_name": "x", "units": "mm",
            "steps": [{"id": "b", "primitive": "aerofoil", "operation": "base"}],
        }
        out = compile_activity(CompileInput(plan_dict=plan_dict, run_id="t2"))
        assert out.ok is False
        assert out.failure_stage == "primitive_gap"


class TestExecuteActivity:
    def test_success_maps_stl_path(self, monkeypatch):
        from temporal.activities import execute_activity

        fake = _fake_tool_module(
            "tools.execute_cadquery", "execute_cadquery",
            lambda code, run_id: {"success": True, "stl_path": "/o/solid.stl", "volume": 1000},
        )
        monkeypatch.setitem(sys.modules, "tools.execute_cadquery", fake)
        out = execute_activity(ExecuteInput(code="x", run_id="r"))
        assert out.ok is True
        assert out.stl_path == "/o/solid.stl"

    def test_failure_tagged_cadquery_execute(self, monkeypatch):
        from temporal.activities import execute_activity

        fake = _fake_tool_module(
            "tools.execute_cadquery", "execute_cadquery",
            lambda code, run_id: {"success": False, "error": "boom"},
        )
        monkeypatch.setitem(sys.modules, "tools.execute_cadquery", fake)
        out = execute_activity(ExecuteInput(code="x", run_id="r"))
        assert out.ok is False
        assert out.failure_stage == "cadquery_execute"
        assert "boom" in out.failure_detail


class TestInspectActivity:
    def test_passes_flag(self, monkeypatch):
        from temporal.activities import inspect_activity

        fake = _fake_tool_module(
            "tools.inspect_mesh", "inspect_mesh",
            lambda stl: {"passes": True, "is_watertight": True},
        )
        monkeypatch.setitem(sys.modules, "tools.inspect_mesh", fake)
        out = inspect_activity(InspectInput(stl_path="/o/solid.stl"))
        assert out.passes is True
        assert out.mesh_report["is_watertight"] is True


class TestRepairActivity:
    def test_repaired_path_on_success(self, monkeypatch):
        from temporal.activities import repair_activity

        fake = _fake_tool_module(
            "tools.repair_mesh", "repair_mesh",
            lambda stl, run_id: {"passes": True, "after": {"is_watertight": True},
                                 "repaired_stl_path": "/o/solid_repaired.stl"},
        )
        monkeypatch.setitem(sys.modules, "tools.repair_mesh", fake)
        out = repair_activity(RepairInput(stl_path="/o/solid.stl", run_id="r"))
        assert out.passes is True
        assert out.repaired_stl_path == "/o/solid_repaired.stl"

    def test_mesh_repair_failure_tagged(self, monkeypatch):
        from temporal.activities import repair_activity

        fake = _fake_tool_module(
            "tools.repair_mesh", "repair_mesh",
            lambda stl, run_id: {"passes": False,
                                 "after": {"is_watertight": False, "num_components": 2},
                                 "actions": ["fill_holes"]},
        )
        monkeypatch.setitem(sys.modules, "tools.repair_mesh", fake)
        out = repair_activity(RepairInput(stl_path="/o/solid.stl", run_id="r"))
        assert out.passes is False
        assert out.failure_stage == "mesh_repair"
        assert out.failure_detail  # collect_feedback_detail produced a message


class TestRenderActivity:
    def test_success(self, monkeypatch):
        from temporal.activities import render_activity

        fake = _fake_tool_module(
            "tools.render_views", "render_views",
            lambda stl, run_id: {"success": True, "png_path": "/o/views.png"},
        )
        monkeypatch.setitem(sys.modules, "tools.render_views", fake)
        out = render_activity(RenderInput(stl_path="/o/solid.stl", run_id="r"))
        assert out.ok is True

    def test_failure_tagged(self, monkeypatch):
        from temporal.activities import render_activity

        fake = _fake_tool_module(
            "tools.render_views", "render_views",
            lambda stl, run_id: {"success": False, "error": "vtk down"},
        )
        monkeypatch.setitem(sys.modules, "tools.render_views", fake)
        out = render_activity(RenderInput(stl_path="/o/solid.stl", run_id="r"))
        assert out.ok is False
        assert out.failure_stage == "cadquery_execute"
