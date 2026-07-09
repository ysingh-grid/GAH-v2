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


def test_invalid_operation_rejected_by_schema():
    """A bogus PrimitiveStep operation fails at schema validation (not the compiler).

    The legacy 'finish' enum value was removed — finish ops are now FinishSteps.
    An unknown operation must be caught up-front by pydantic.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        plan_from_dict(
            {
                "part_name": "x",
                "steps": [
                    {"id": "b", "primitive": "box", "operation": "base"},
                    {"id": "f", "primitive": "box", "operation": "finish"},
                ],
            }
        )


def test_intersect_compiles_to_boolean_and():
    """The intersect operation emits result.intersect(...) — boolean AND."""
    plan = plan_from_dict(
        {
            "part_name": "lens",
            "steps": [
                {"id": "b", "primitive": "box", "operation": "base",
                 "parameters": {"length": 50, "width": 50, "height": 30}, "position": [0, 0, 15]},
                {"id": "s", "primitive": "sphere", "operation": "intersect",
                 "parameters": {"radius": 32}, "position": [0, 0, 15]},
            ],
        }
    )
    code = compile_plan_to_cadquery(plan, LIBRARY)
    assert "result.intersect(" in code


def test_compile_twist_extrude_emits_twistextrude():
    """twist_extrude template should produce .twistExtrude() in the output."""
    plan = plan_from_dict(
        {
            "part_name": "twisted_column",
            "steps": [
                {
                    "id": "col",
                    "primitive": "twist_extrude",
                    "operation": "base",
                    "parameters": {
                        "profile": [[-5, -5], [5, -5], [5, 5], [-5, 5]],
                        "height": 40.0,
                        "angle": 90.0,
                        "smooth": False,
                    },
                }
            ],
        }
    )
    code = compile_plan_to_cadquery(plan, LIBRARY)
    assert "twistExtrude(40.0, 90.0)" in code


def test_compile_slot_extrude_emits_slot2d():
    """slot_extrude template should produce .slot2D() in the output."""
    plan = plan_from_dict(
        {
            "part_name": "slot_part",
            "steps": [
                {
                    "id": "slot",
                    "primitive": "slot_extrude",
                    "operation": "base",
                    "parameters": {"width": 20.0, "height": 8.0, "depth": 5.0},
                }
            ],
        }
    )
    code = compile_plan_to_cadquery(plan, LIBRARY)
    assert "slot2D(20.0, 8.0)" in code
    assert ".extrude(5.0)" in code


def test_compile_ellipse_extrude_emits_ellipse():
    """ellipse_extrude template should produce .ellipse() in the output."""
    plan = plan_from_dict(
        {
            "part_name": "oval_base",
            "steps": [
                {
                    "id": "oval",
                    "primitive": "ellipse_extrude",
                    "operation": "base",
                    "parameters": {"x_radius": 10.0, "y_radius": 6.0, "height": 15.0},
                }
            ],
        }
    )
    code = compile_plan_to_cadquery(plan, LIBRARY)
    assert "ellipse(10.0, 6.0)" in code


def test_compile_text_3d_emits_text():
    """text_3d template should produce .text('HELLO', ...) in the output."""
    plan = plan_from_dict(
        {
            "part_name": "label",
            "steps": [
                {
                    "id": "lbl",
                    "primitive": "text_3d",
                    "operation": "base",
                    "parameters": {
                        "text": "HELLO",
                        "font_size": 8.0,
                        "depth": 1.5,
                        "font": "Arial",
                    },
                }
            ],
        }
    )
    code = compile_plan_to_cadquery(plan, LIBRARY)
    assert "'HELLO'" in code
    assert "text(" in code


def test_compile_arc_extrude_emits_arc_profile_wp():
    """arc_extrude template should produce _arc_profile_wp(...) in the output."""
    plan = plan_from_dict(
        {
            "part_name": "d_profile",
            "steps": [
                {
                    "id": "body",
                    "primitive": "arc_extrude",
                    "operation": "base",
                    "parameters": {
                        "segments": [
                            ["line", 10.0, 0.0],
                            ["arc3", 10.0, 5.0, 0.0, 10.0],
                            ["line", -10.0, 10.0],
                            ["arc3", -10.0, 5.0, 0.0, 0.0],
                        ],
                        "height": 8.0,
                    },
                }
            ],
        }
    )
    code = compile_plan_to_cadquery(plan, LIBRARY)
    assert "_arc_profile_wp(" in code
    assert ".extrude(8.0)" in code


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


# ── integration: the 5 newly added primitives actually run through real OCCT ──
# Codegen tests above only assert the emitted string; these prove the emitted
# CadQuery call is real (correct method name, correct arg order) and produces a
# valid, non-degenerate solid — not just text that looks plausible.


def test_twist_extrude_executes_to_valid_twisted_solid(_cadquery_available):
    plan = plan_from_dict(
        {
            "part_name": "twisted_column",
            "steps": [
                {
                    "id": "col",
                    "primitive": "twist_extrude",
                    "operation": "base",
                    "parameters": {
                        "profile": [[-5, -5], [5, -5], [5, 5], [-5, 5]],
                        "height": 40.0,
                        "angle": 90.0,
                    },
                }
            ],
        }
    )
    result = _run(plan)
    assert result["success"], result.get("error")
    # twistExtrude is a ruled sweep: cross-sectional area is constant along the
    # twist, so volume == area * height (10x10x40=4000) even though the shape
    # is sheared — a near-4000 volume proves a real, non-degenerate solid.
    assert result["volume"] == pytest.approx(4000.0, rel=0.01)


def test_slot_extrude_executes_to_stadium_volume(_cadquery_available):
    plan = plan_from_dict(
        {
            "part_name": "slot_part",
            "steps": [
                {
                    "id": "slot",
                    "primitive": "slot_extrude",
                    "operation": "base",
                    "parameters": {"width": 20.0, "height": 8.0, "depth": 5.0},
                }
            ],
        }
    )
    result = _run(plan)
    assert result["success"], result.get("error")
    # slot2D(length=20, diameter=8): rect(12x8) + 2 half-circles(r=4) = 96 + 50.27 = 146.27; *5mm depth
    assert result["volume"] == pytest.approx(146.27 * 5.0, rel=0.02)


def test_ellipse_extrude_executes_to_correct_volume(_cadquery_available):
    plan = plan_from_dict(
        {
            "part_name": "oval_base",
            "steps": [
                {
                    "id": "oval",
                    "primitive": "ellipse_extrude",
                    "operation": "base",
                    "parameters": {"x_radius": 10.0, "y_radius": 6.0, "height": 15.0},
                }
            ],
        }
    )
    result = _run(plan)
    assert result["success"], result.get("error")
    import math

    assert result["volume"] == pytest.approx(math.pi * 10.0 * 6.0 * 15.0, rel=0.01)


def test_text_3d_executes_to_valid_solid(_cadquery_available):
    plan = plan_from_dict(
        {
            "part_name": "label",
            "steps": [
                {
                    "id": "lbl",
                    "primitive": "text_3d",
                    "operation": "base",
                    "parameters": {"text": "HI", "font_size": 8.0, "depth": 1.5},
                }
            ],
        }
    )
    result = _run(plan)
    assert result["success"], result.get("error")
    assert result["volume"] > 0


@pytest.mark.parametrize(
    "segments",
    [
        pytest.param(
            [["line", 10.0, 0.0], ["arc3", 10.0, 5.0, 0.0, 10.0], ["line", -10.0, 10.0],
             ["arc3", -10.0, 5.0, 0.0, 0.0]],
            id="arc3_three_point",
        ),
        pytest.param(
            [["line", 10, 0], ["rarc", 10, 10, 5], ["line", 0, 10], ["line", 0, 0]],
            id="rarc_radius",
        ),
        pytest.param(
            [["line", 10, 0], ["sarc", 10, 10, 2], ["line", 0, 10], ["line", 0, 0]],
            id="sarc_sagitta",
        ),
        pytest.param(
            [["line", 10, 0], ["tarc", 10, 10], ["line", 0, 10], ["line", 0, 0]],
            id="tarc_tangent",
        ),
    ],
)
def test_arc_extrude_executes_for_every_segment_kind(_cadquery_available, segments):
    """Every arc-drawing command _arc_profile_wp supports (line/arc3/rarc/sarc/tarc)
    must produce a valid solid through real CadQuery — not just arc3."""
    plan = plan_from_dict(
        {
            "part_name": "d_profile",
            "steps": [
                {
                    "id": "body",
                    "primitive": "arc_extrude",
                    "operation": "base",
                    "parameters": {"segments": segments, "height": 8.0},
                }
            ],
        }
    )
    result = _run(plan)
    assert result["success"], result.get("error")
    assert result["volume"] > 0


def test_rarray_pattern_executes_to_correct_hole_count(_cadquery_available):
    """A 2x2 rarray of cut holes removes 4x one hole's volume, not 1x or 2x."""
    plan = plan_from_dict(
        {
            "part_name": "pcb_plate",
            "steps": [
                {
                    "id": "base",
                    "primitive": "box",
                    "operation": "base",
                    "parameters": {"length": 100.0, "width": 80.0, "height": 5.0},
                },
                {
                    "id": "holes",
                    "primitive": "cylinder",
                    "operation": "cut",
                    "parameters": {"radius": 2.0, "height": 7.0},
                    "position": [-30.0, -20.0, 0.0],
                    "pattern": {
                        "type": "rarray",
                        "x_spacing": 60.0,
                        "y_spacing": 40.0,
                        "x_count": 2,
                        "y_count": 2,
                    },
                },
            ],
        }
    )
    result = _run(plan)
    assert result["success"], result.get("error")
    import math

    plate_vol = 100.0 * 80.0 * 5.0
    one_hole_vol = math.pi * 2.0**2 * 5.0  # only the 5mm plate thickness is actually removed
    expected = plate_vol - 4 * one_hole_vol
    assert result["volume"] == pytest.approx(expected, rel=0.02)
