"""Host auto-hollow synthesis — general wall shrink, no product recipes."""

from __future__ import annotations

from runtime.auto_hollow import (
    plan_implies_through_path,
    synthesize_cavity_plan,
)
from runtime.metrics_gate import plan_has_cavity_strategy, resolve_hollow_requirement
from runtime.schema import plan_from_dict


def _adapter_outer_plan():
    return plan_from_dict(
        {
            "part_name": "transition_adapter",
            "steps": [
                {
                    "id": "base_flange",
                    "primitive": "box",
                    "operation": "base",
                    "parameters": {"height": 3, "length": 70, "width": 50},
                    "position": [0, 0, 1.5],
                },
                {
                    "id": "transition",
                    "primitive": "rect_to_round",
                    "operation": "union",
                    "parameters": {
                        "base_length": 60,
                        "base_width": 40,
                        "height": 50,
                        "top_diameter": 30,
                    },
                    "position": [0, 0, 3],
                },
                {
                    "id": "top_collar",
                    "primitive": "cylinder",
                    "operation": "union",
                    "parameters": {"height": 10, "radius": 15},
                    "position": [0, 0, 58],
                },
            ],
        }
    )


def test_rect_to_round_plan_implies_through_path():
    assert plan_implies_through_path(_adapter_outer_plan()) is True


def test_box_only_does_not_imply_through_path():
    plan = plan_from_dict(
        {
            "part_name": "block",
            "steps": [
                {
                    "id": "b",
                    "primitive": "box",
                    "operation": "base",
                    "parameters": {"length": 10, "width": 10, "height": 10},
                }
            ],
        }
    )
    assert plan_implies_through_path(plan) is False


def test_synthesize_cavity_adds_cut_steps():
    outer = _adapter_outer_plan()
    assert plan_has_cavity_strategy(outer) is False
    hollowed = synthesize_cavity_plan(outer, wall_mm=2.0)
    assert hollowed is not None
    assert plan_has_cavity_strategy(hollowed) is True
    cuts = [
        s
        for s in hollowed.steps
        if getattr(s, "operation", None) and s.operation.value == "cut"
    ]
    assert len(cuts) >= 2  # at least flange + transition (+ collar)


def test_resolve_hollow_from_structural_plan():
    outer = _adapter_outer_plan()
    # Prompt has no hollow keywords; plan structure still requires hollow.
    t = resolve_hollow_requirement(
        "Design a transition with rect loft and neck to Z=63",
        "",
        outer,
    )
    assert t.requires_hollow is True


def test_resolve_hollow_none_override():
    outer = _adapter_outer_plan()
    t = resolve_hollow_requirement(
        "hollow duct please",
        "",
        outer,
        through_path="none",
    )
    assert t.requires_hollow is False


def test_auto_hollow_adapter_executes_one_solid_lower_volume():
    """Host auto-cavity on loft stack → 1 solid, volume ≪ solid fill."""
    import shutil

    import pytest

    pytest.importorskip("cadquery")
    from runtime.compile_cadquery import compile_plan_to_cadquery
    from runtime.schema import load_library
    from tools.artifacts import new_run_id, run_dir
    from tools.execute_cadquery import execute_cadquery

    outer = _adapter_outer_plan()
    hollowed = synthesize_cavity_plan(outer, wall_mm=2.0)
    assert hollowed is not None
    code = compile_plan_to_cadquery(hollowed, load_library())
    rid = new_run_id("test_auto_hollow_exec")
    try:
        out = execute_cadquery(code, rid)
        assert out.get("success") is True, out.get("error")
        assert out.get("num_solids") == 1
        assert out.get("volume", 0) < 40000  # solid ~91k
    finally:
        shutil.rmtree(run_dir(rid), ignore_errors=True)
