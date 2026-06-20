"""Unit tests for runtime/schema.py — PrimitivePlan structural + semantic validation."""

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


def test_plan_with_two_base_steps_raises():
    bad = {"part_name": "x", "steps": [_box_base("a"), _box_base("b")]}
    with pytest.raises(ValidationError, match="exactly one 'base'"):
        plan_from_dict(bad)


def test_base_step_not_first_raises():
    bad = {
        "part_name": "x",
        "steps": [
            {"id": "hole", "primitive": "cylinder", "operation": "cut", "parameters": {}},
            _box_base("body"),
        ],
    }
    with pytest.raises(ValidationError, match="must be the first step"):
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


def test_pattern_count_below_two_raises():
    with pytest.raises(ValidationError):
        Pattern(type=PatternType.polar, count=1)


# ── semantic validation against the library ──────────────────────────────────


def test_valid_plan_against_real_library_has_no_errors():
    library = schema.load_library()
    plan = plan_from_dict({"part_name": "cube", "steps": [_box_base()]})
    assert validate_plan_against_library(plan, library) == []


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
    assert len(library) == 20
    assert "box" in library
    assert "profile_extrude" in library
    assert "revolve" in library
