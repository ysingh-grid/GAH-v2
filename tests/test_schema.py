"""Real-world schema tests for PrimitivePlan structural + semantic validation."""

import pytest
from pydantic import ValidationError

from runtime import schema
from runtime.schema import (
    Operation,
    Pattern,
    PatternType,
    PrimitivePlan,
    plan_from_dict,
    validate_plan_against_library,
)
from tests.real_world_scenarios import mounting_plate_with_four_holes, open_electronics_enclosure


def _box_base(step_id: str = "body", **params: float) -> dict:
    return {
        "id": step_id,
        "primitive": "box",
        "operation": "base",
        "parameters": params or {"length": 60.0, "width": 60.0, "height": 60.0},
    }


# ── structural validation ────────────────────────────────────────────────────


def test_minimal_single_base_plan_is_valid():
    plan = plan_from_dict({"part_name": "cube", "steps": [_box_base()]})
    assert isinstance(plan, PrimitivePlan)
    assert plan.units == "mm"
    assert plan.steps[0].operation is Operation.base


def test_plan_with_zero_steps_raises():
    with pytest.raises(ValidationError):
        plan_from_dict({"part_name": "empty", "steps": []})


def test_plan_with_no_base_step_raises():
    bad = {
        "part_name": "x",
        "steps": [{"id": "a", "primitive": "box", "operation": "union", "parameters": {}}],
    }
    with pytest.raises(ValidationError, match="exactly one 'base'"):
        plan_from_dict(bad)


def test_plan_with_two_base_steps_is_coerced_to_one_base_one_union():
    """A Case-A multi-solid plan (bolt+nut, flange-kit) naturally has N bodies,
    each reading as its own 'base' — the schema folds every base after the
    first into 'union' instead of rejecting the plan (see
    PrimitivePlan._coerce_extra_bases)."""
    multi = {"part_name": "x", "steps": [_box_base("a"), _box_base("b"), _box_base("c")]}
    plan = plan_from_dict(multi)
    assert plan.steps[0].id == "a"
    assert plan.steps[0].operation is Operation.base
    assert plan.steps[1].operation is Operation.union
    assert plan.steps[2].operation is Operation.union


def test_base_step_not_first_raises():
    bad = {
        "part_name": "x",
        "steps": [
            {"id": "hole", "primitive": "cylinder", "operation": "cut", "parameters": {}},
            _box_base("body"),
        ],
    }
    with pytest.raises(ValidationError, match="must be the first primitive step"):
        plan_from_dict(bad)


def test_duplicate_step_ids_raise():
    bad = {
        "part_name": "x",
        "steps": [
            _box_base("dup"),
            {"id": "dup", "primitive": "cylinder", "operation": "cut", "parameters": {}},
        ],
    }
    with pytest.raises(ValidationError, match="unique"):
        plan_from_dict(bad)


def test_non_mm_units_raise():
    with pytest.raises(ValidationError, match="mm"):
        plan_from_dict({"part_name": "x", "units": "inch", "steps": [_box_base()]})


def test_unknown_extra_field_is_forbidden():
    with pytest.raises(ValidationError):
        plan_from_dict({"part_name": "x", "steps": [_box_base()], "bogus": 1})


# ── pattern rules ────────────────────────────────────────────────────────────


def test_pattern_on_union_step_is_valid():
    plan = plan_from_dict(
        {
            "part_name": "bolt_circle",
            "steps": [
                _box_base(),
                {
                    "id": "holes",
                    "primitive": "cylinder",
                    "operation": "cut",
                    "parameters": {"radius": 2.0, "height": 80.0},
                    "pattern": {"type": "polar", "count": 6},
                },
            ],
        }
    )
    assert plan.steps[1].pattern is not None
    assert plan.steps[1].pattern.type is PatternType.polar
    assert plan.steps[1].pattern.count == 6


def test_pattern_on_base_step_raises():
    bad = {
        "part_name": "x",
        "steps": [
            {
                "id": "body",
                "primitive": "box",
                "operation": "base",
                "parameters": {},
                "pattern": {"type": "linear", "count": 3},
            }
        ],
    }
    with pytest.raises(ValidationError, match="only valid on union/cut"):
        plan_from_dict(bad)


def test_pattern_count_below_two_raises_for_polar():
    with pytest.raises(ValidationError):
        Pattern(type=PatternType.polar, count=1)


def test_pattern_count_below_two_raises_for_linear():
    with pytest.raises(ValidationError):
        Pattern(type=PatternType.linear, count=1)


def test_rarray_pattern_is_valid():
    """rarray accepts x_count x y_count grid with no count field needed."""
    pattern = Pattern(
        type=PatternType.rarray,
        x_spacing=30.0,
        y_spacing=20.0,
        x_count=2,
        y_count=2,
    )
    assert pattern.type is PatternType.rarray
    assert pattern.x_count == 2
    assert pattern.y_count == 2


def test_rarray_pattern_1x1_raises():
    """rarray with x_count=1, y_count=1 gives total=1, which is invalid."""
    with pytest.raises(ValidationError, match="x_count \\* y_count >= 2"):
        Pattern(type=PatternType.rarray, x_count=1, y_count=1)


def test_rarray_on_step_compiles_to_grid():
    """An rarray pattern on a union step emits _rarray(...) in compiled code."""
    from runtime.compile_cadquery import compile_plan_to_cadquery
    from runtime import schema

    library = schema.load_library()
    plan = plan_from_dict(
        {
            "part_name": "pcb_plate",
            "steps": [
                {
                    "id": "base",
                    "primitive": "box",
                    "operation": "base",
                    "parameters": {"length": 80.0, "width": 60.0, "height": 5.0},
                },
                {
                    "id": "holes",
                    "primitive": "cylinder",
                    "operation": "cut",
                    "parameters": {"radius": 1.5, "height": 7.0},
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
    code = compile_plan_to_cadquery(plan, library)
    assert "_rarray(s1, 60.0, 40.0, 2, 2)" in code


# ── semantic validation against the library ──────────────────────────────────


def test_mounting_plate_plan_against_real_library_has_no_errors():
    library = schema.load_library()
    scenario = mounting_plate_with_four_holes()
    assert validate_plan_against_library(scenario.plan, library) == []


def test_open_enclosure_plan_against_real_library_has_no_errors():
    library = schema.load_library()
    scenario = open_electronics_enclosure()
    assert validate_plan_against_library(scenario.plan, library) == []


def test_unknown_primitive_reports_primitive_gap():
    library = schema.load_library()
    plan = plan_from_dict(
        {
            "part_name": "impeller",
            "steps": [
                {"id": "blade", "primitive": "aerofoil", "operation": "base", "parameters": {}}
            ],
        }
    )
    errors = validate_plan_against_library(plan, library)
    assert len(errors) == 1
    assert "primitive_gap" in errors[0]


def test_unknown_parameter_is_reported():
    library = schema.load_library()
    plan = plan_from_dict({"part_name": "x", "steps": [_box_base("body", length=10.0, bogus=5.0)]})
    errors = validate_plan_against_library(plan, library)
    assert any("unknown parameter 'bogus'" in e for e in errors)


def test_int_param_given_float_is_reported():
    library = schema.load_library()
    # prism.sides is typed int in the library
    plan = plan_from_dict(
        {
            "part_name": "pentaprism",
            "steps": [
                {
                    "id": "body",
                    "primitive": "prism",
                    "operation": "base",
                    "parameters": {"sides": 5.5, "radius": 5.0, "height": 10.0},
                }
            ],
        }
    )
    errors = validate_plan_against_library(plan, library)
    assert any("expects int" in e for e in errors)


def test_load_library_returns_full_catalog():
    library = schema.load_library()
    assert isinstance(library, dict)
    assert len(library) == 31
    assert "box" in library
    assert "profile_extrude" in library
    assert "loft" in library
    assert "sweep" in library
    assert "revolve" in library
    assert "twist_extrude" in library
    assert "slot_extrude" in library
    assert "ellipse_extrude" in library
    assert "text_3d" in library
    assert "arc_extrude" in library
