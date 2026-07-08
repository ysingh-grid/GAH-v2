"""M4: profile_extrude + revolve primitives — compile shape + real CadQuery run.

Pattern (polar/linear) is already covered in test_compile_cadquery.py; this file
proves the profile force-multipliers compile and execute to sane geometry.
"""

import math
import shutil

import pytest

from runtime import schema
from runtime.compile_cadquery import compile_plan_to_cadquery
from runtime.schema import plan_from_dict, validate_plan_against_library

LIBRARY = schema.load_library()


def _run(plan):
    from tools.artifacts import new_run_id, run_dir
    from tools.execute_cadquery import execute_cadquery

    run_id = new_run_id("test_profile")
    code = compile_plan_to_cadquery(plan, LIBRARY)
    try:
        return execute_cadquery(code, run_id)
    finally:
        shutil.rmtree(run_dir(run_id), ignore_errors=True)


def _triangle_extrude():
    return plan_from_dict(
        {
            "part_name": "tri_prism",
            "steps": [
                {
                    "id": "body",
                    "primitive": "profile_extrude",
                    "operation": "base",
                    "parameters": {
                        "profile": [[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]],
                        "height": 5.0,
                    },
                }
            ],
        }
    )


def _revolved_cylinder():
    return plan_from_dict(
        {
            "part_name": "turned_cyl",
            "steps": [
                {
                    "id": "body",
                    "primitive": "revolve",
                    "operation": "base",
                    "parameters": {
                        "profile": [[0.0, 0.0], [5.0, 0.0], [5.0, 10.0], [0.0, 10.0]],
                        "angle": 360.0,
                    },
                }
            ],
        }
    )


# ── schema / compile ─────────────────────────────────────────────────────────


def test_profile_primitives_validate_against_library():
    assert validate_plan_against_library(_triangle_extrude(), LIBRARY) == []
    assert validate_plan_against_library(_revolved_cylinder(), LIBRARY) == []


def test_profile_extrude_compiles_polyline_and_extrude():
    code = compile_plan_to_cadquery(_triangle_extrude(), LIBRARY)
    # default smooth=False -> straight polyline profile via the shared builder
    assert "_profile_wp([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]], smooth=False).extrude(5.0)" in code


def test_revolve_compiles_with_axis():
    code = compile_plan_to_cadquery(_revolved_cylinder(), LIBRARY)
    assert "_profile_wp(" in code
    assert ".revolve(360.0, (0, 0, 0), (0, 1, 0))" in code


# ── real CadQuery execution ──────────────────────────────────────────────────


@pytest.fixture
def _cadquery_available():
    return pytest.importorskip("cadquery")


def test_triangle_extrude_executes_to_correct_volume(_cadquery_available):
    result = _run(_triangle_extrude())
    assert result["success"], result.get("error")
    # right triangle area = 0.5 * 10 * 10 = 50; * height 5 = 250
    assert abs(result["volume"] - 250.0) < 1.0


def test_revolve_executes_to_cylinder_volume(_cadquery_available):
    result = _run(_revolved_cylinder())
    assert result["success"], result.get("error")
    # 5x10 rectangle revolved about the Y axis -> cylinder r=5, h=10
    assert abs(result["volume"] - math.pi * 25.0 * 10.0) < 5.0


# ── smooth (spline) profile mode ─────────────────────────────────────────────


def _smooth_revolve():
    """A curved-silhouette revolve (vase-like) with smooth=True."""
    return plan_from_dict(
        {
            "part_name": "vase",
            "steps": [
                {
                    "id": "body",
                    "primitive": "revolve",
                    "operation": "base",
                    "parameters": {
                        "profile": [
                            [0.0, 0.0], [30.0, 0.0], [32.0, 20.0], [20.0, 45.0],
                            [18.0, 60.0], [25.0, 75.0], [24.0, 90.0], [0.0, 90.0],
                        ],
                        "angle": 360.0,
                        "smooth": True,
                    },
                }
            ],
        }
    )


def test_smooth_profile_emits_spline_not_polyline():
    code = compile_plan_to_cadquery(_smooth_revolve(), LIBRARY)
    # smooth=True -> the builder splines the points; the straight polyline path is gone
    assert "smooth=True" in code
    assert "polyline" not in code.split("_PREAMBLE", 1)[-1].split("result =")[-1]


def test_smooth_revolve_executes_to_valid_curved_solid(_cadquery_available):
    result = _run(_smooth_revolve())
    assert result["success"], result.get("error")
    # a smooth surface of revolution is watertight with meaningful volume
    assert result["volume"] > 1000.0
