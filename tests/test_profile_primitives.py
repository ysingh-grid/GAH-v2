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


# ── sparse-profile auto-densification ────────────────────────────────────────
# Live production bug: a spoon bowl's loft_between used 8 elliptical control
# points per end. Each end was individually smooth on its own, but the bottom
# and top profiles had DIFFERENT aspect ratios (5:9 -> 19:29 — the bowl legitimately
# reshapes, not just scales, as it widens; a normal design choice), and the
# lofted surface BETWEEN two shape-changing 8-point splines came out visibly
# faceted into a rounded octagon — confirmed geometric, not a render artifact
# (finer STL tessellation made zero difference; every face's geomType stayed
# BSPLINE throughout). 16+ points fixed it completely. The planner can't be
# relied on to always remember to emit enough points (the same failure mode
# smooth=True itself had before it got explicit skill guidance), so the fix is
# a deterministic compiler-level floor: _densify_closed_points auto-resamples
# any sparse smooth profile before it reaches the loft/spline builder.


def _bowl_plan(n_points, bottom_r=(5.0, 9.0), top_r=(19.0, 29.0)):
    import math

    def ellipse_pts(a, b, n):
        return [
            [round(a * math.cos(2 * math.pi * i / n), 3), round(b * math.sin(2 * math.pi * i / n), 3)]
            for i in range(n)
        ]

    return plan_from_dict(
        {
            "part_name": "bowl",
            "steps": [
                {
                    "id": "bowl",
                    "primitive": "loft_between",
                    "operation": "base",
                    "parameters": {
                        "profile_bottom": ellipse_pts(*bottom_r, n_points),
                        "profile_top": ellipse_pts(*top_r, n_points),
                        "height": 5.0,
                        "smooth_bottom": True,
                        "smooth_top": True,
                    },
                }
            ],
        }
    )


def test_sparse_reshaping_loft_between_converges_to_dense_reference(_cadquery_available):
    """The regression case: only 8 control points per end, aspect ratio changes
    bottom->top. Auto-densification must bring this within a couple percent of
    a directly-dense (32pt) reference of the same intended ellipse — proving
    the fix reaches the SAME smooth shape, not merely "a" different shape."""
    sparse = _run(_bowl_plan(8))
    dense = _run(_bowl_plan(32))
    assert sparse["success"], sparse.get("error")
    assert dense["success"], dense.get("error")
    rel_diff = abs(sparse["volume"] - dense["volume"]) / dense["volume"]
    assert rel_diff < 0.03, f"8pt vs 32pt volume differs by {rel_diff:.1%} — densification not converging"


def test_densify_is_a_near_identity_on_already_dense_profiles(_cadquery_available):
    """Densifying an ALREADY-dense profile must not distort it — the floor only
    engages below _MIN_SMOOTH_POINTS, and even when it does engage it resamples
    the same curve rather than fitting a different one."""
    at_threshold = _run(_bowl_plan(16))
    above_threshold = _run(_bowl_plan(32))
    assert at_threshold["success"] and above_threshold["success"]
    rel_diff = abs(at_threshold["volume"] - above_threshold["volume"]) / above_threshold["volume"]
    assert rel_diff < 0.02


def test_densify_helper_resamples_only_when_sparse():
    """Unit-level check of _densify_closed_points itself (lives inside the
    compiler's _PREAMBLE, exec'd into the generated script's namespace)."""
    pytest.importorskip("cadquery")
    from runtime.compile_cadquery import _PREAMBLE

    ns = {}
    exec(_PREAMBLE, ns)
    densify = ns["_densify_closed_points"]

    sparse_pts = [(0.0, 9.0), (3.53, 6.36), (5.0, 0.0), (3.53, -6.36),
                  (0.0, -9.0), (-3.53, -6.36), (-5.0, 0.0), (-3.53, 6.36)]
    out = densify(sparse_pts, 16)
    assert len(out) == 16

    already_dense = [(float(i), float(i)) for i in range(20)]
    out2 = densify(already_dense, 16)
    assert out2 == already_dense  # below-threshold target on an already-dense input: untouched
