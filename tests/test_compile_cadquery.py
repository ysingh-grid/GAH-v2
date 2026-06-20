"""Tests for runtime/compile_cadquery.py.

Two layers:
* pure: the generated code string has the right shape (no CadQuery needed);
* integration: compile a plan and actually run it through execute_cadquery to
  prove plan -> STL with sane geometry (needs CadQuery in the env).
"""

import shutil

import pytest

from runtime import schema
from runtime.compile_cadquery import CompileError, compile_plan_to_cadquery
from runtime.schema import plan_from_dict

LIBRARY = schema.load_library()


def _cube_plan(size: float = 60.0):
    return plan_from_dict(
        {
            "part_name": "cube",
            "steps": [
                {
                    "id": "body",
                    "primitive": "box",
                    "operation": "base",
                    "parameters": {"length": size, "width": size, "height": size},
                }
            ],
        }
    )


def _bolt_circle_plan():
    return plan_from_dict(
        {
            "part_name": "bolt_plate",
            "steps": [
                {
                    "id": "plate",
                    "primitive": "box",
                    "operation": "base",
                    "parameters": {"length": 60.0, "width": 60.0, "height": 10.0},
                },
                {
                    "id": "holes",
                    "primitive": "cylinder",
                    "operation": "cut",
                    "parameters": {"radius": 2.0, "height": 20.0},
                    "position": [20.0, 0.0, 0.0],
                    "pattern": {"type": "polar", "count": 6},
                },
            ],
        }
    )


# ── pure compile-output tests ────────────────────────────────────────────────


def test_compile_cube_emits_runnable_skeleton():
    code = compile_plan_to_cadquery(_cube_plan(), LIBRARY)
    assert "import cadquery as cq" in code
    assert 'cq.Workplane("XY").box(60.0, 60.0, 60.0)' in code
    assert "result = s0" in code


def test_compile_places_with_rotate_and_translate():
    code = compile_plan_to_cadquery(_cube_plan(), LIBRARY)
    assert "_place(s0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))" in code


def test_compile_polar_pattern_emits_polar_call_and_cut():
    code = compile_plan_to_cadquery(_bolt_circle_plan(), LIBRARY)
    assert "_polar(s1, 6, (0.0, 0.0, 1.0), 360.0)" in code
    assert "result = result.cut(s1)" in code


def test_compile_defaults_fill_missing_params():
    plan = plan_from_dict(
        {"part_name": "c", "steps": [{"id": "b", "primitive": "cylinder", "operation": "base"}]}
    )
    code = compile_plan_to_cadquery(plan, LIBRARY)
    # cylinder defaults are height=10.0, radius=5.0 -> template cylinder(height, radius)
    assert 'cq.Workplane("XY").cylinder(10.0, 5.0)' in code


def test_compile_missing_primitive_raises_compileerror():
    plan = plan_from_dict(
        {"part_name": "x", "steps": [{"id": "b", "primitive": "aerofoil", "operation": "base"}]}
    )
    with pytest.raises(CompileError, match="primitive_gap"):
        compile_plan_to_cadquery(plan, LIBRARY)


def test_compile_finish_op_raises_until_m4():
    plan = plan_from_dict(
        {
            "part_name": "x",
            "steps": [
                {"id": "b", "primitive": "box", "operation": "base"},
                {"id": "f", "primitive": "box", "operation": "finish"},
            ],
        }
    )
    with pytest.raises(CompileError, match="not supported"):
        compile_plan_to_cadquery(plan, LIBRARY)


# ── integration: compile -> execute_cadquery -> real STL ─────────────────────


@pytest.fixture
def _cadquery_available():
    return pytest.importorskip("cadquery")


def _run(plan):
    from tools.artifacts import new_run_id, run_dir
    from tools.execute_cadquery import execute_cadquery

    run_id = new_run_id("test_compile")
    code = compile_plan_to_cadquery(plan, LIBRARY)
    try:
        result = execute_cadquery(code, run_id)
    finally:
        shutil.rmtree(run_dir(run_id), ignore_errors=True)
    return result


def test_compiled_cube_executes_to_correct_volume(_cadquery_available):
    result = _run(_cube_plan(60.0))
    assert result["success"], result.get("error")
    assert abs(result["volume"] - 60.0**3) < 1.0
    assert result["faces_count"] == 6


def test_compiled_bolt_circle_executes_and_removes_material(_cadquery_available):
    solid_volume = 60.0 * 60.0 * 10.0
    result = _run(_bolt_circle_plan())
    assert result["success"], result.get("error")
    # six holes drilled -> strictly less material than the solid plate
    assert result["volume"] < solid_volume
    assert result["volume"] > solid_volume * 0.9
