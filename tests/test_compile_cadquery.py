"""Real-world tests for PrimitivePlan -> CadQuery compilation.

The cheap assertions still inspect source text, but the main cases compile
believable product parts and execute them through CadQuery to verify dimensions
and material removal.
"""

import shutil

import pytest

from runtime import schema
from runtime.compile_cadquery import CompileError, compile_plan_to_cadquery
from runtime.schema import plan_from_dict
from tests.real_world_scenarios import (
    bbox_size,
    mounting_plate_with_four_holes,
    open_electronics_enclosure,
)

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


# ── pure compile-output tests ────────────────────────────────────────────────


def test_compile_cube_emits_runnable_skeleton():
    code = compile_plan_to_cadquery(_cube_plan(), LIBRARY)
    assert "import cadquery as cq" in code
    assert 'cq.Workplane("XY").box(60.0, 60.0, 60.0)' in code
    assert "result = s0" in code


def test_compile_places_with_rotate_and_translate():
    code = compile_plan_to_cadquery(_cube_plan(), LIBRARY)
    assert "_place(s0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))" in code


def test_compile_mounting_plate_emits_corner_hole_cuts():
    scenario = mounting_plate_with_four_holes()
    code = compile_plan_to_cadquery(scenario.plan, LIBRARY)
    assert "# part: electronics_mounting_plate" in code
    assert "_linear(s1, 2, (0.0, 36.0, 0.0))" in code
    assert "_linear(s2, 2, (0.0, 36.0, 0.0))" in code
    assert code.count("result = result.cut") == 2


def test_compile_open_enclosure_uses_shell_bosses_and_boss_holes():
    scenario = open_electronics_enclosure()
    code = compile_plan_to_cadquery(scenario.plan, LIBRARY)
    assert ".faces(\">Z\").shell(-2.0)" in code
    assert code.count("result = result.union") == 4
    assert code.count("result = result.cut") == 2


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


def test_compiled_mounting_plate_executes_with_real_dimensions(_cadquery_available):
    scenario = mounting_plate_with_four_holes()
    result = _run(scenario.plan)
    assert result["success"], result.get("error")
    assert bbox_size(result["bbox"], "x") == pytest.approx(scenario.expected_bbox["x"], abs=0.01)
    assert bbox_size(result["bbox"], "y") == pytest.approx(scenario.expected_bbox["y"], abs=0.01)
    assert bbox_size(result["bbox"], "z") == pytest.approx(scenario.expected_bbox["z"], abs=0.01)
    assert result["volume"] < scenario.solid_reference_volume
    assert result["volume"] > scenario.solid_reference_volume * 0.99
