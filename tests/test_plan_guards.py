"""Host construction family + guards — no LLM, no CadQuery."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from runtime.plan_guards import (
    classify_construction_family,
    construction_errors_for_plan,
    extract_vessel_dims_from_plan,
    has_cap_style_secondary_body,
    has_union_after_cavity,
    open_vessel_template_plan,
    open_vessel_violations,
)
from runtime.schema import (
    LibraryBoundPrimitivePlan,
    accept_plan,
    plan_from_dict,
)


def test_classify_bottle_as_open_vessel():
    assert classify_construction_family("design an water bottle") == "open_vessel"
    assert classify_construction_family("make a coffee cup") == "open_vessel"


def test_classify_plate_and_free():
    assert classify_construction_family("design a mounting plate") == "plate_like"
    assert classify_construction_family("design a bracket arm") == "free_csg"


def test_cap_style_secondary_body_detected():
    plan = plan_from_dict(
        {
            "part_name": "b",
            "steps": [
                {
                    "id": "body",
                    "primitive": "cylinder",
                    "operation": "base",
                    "parameters": {"radius": 30, "height": 100},
                },
                {
                    "id": "cap_main",
                    "primitive": "cylinder",
                    "operation": "union",
                    "parameters": {"radius": 20, "height": 15},
                },
            ],
        }
    )
    assert has_cap_style_secondary_body(plan)
    errs = construction_errors_for_plan(plan)
    assert any("cap" in e.lower() for e in errs)


def test_union_after_cavity_detected():
    plan = plan_from_dict(
        {
            "part_name": "b",
            "steps": [
                {
                    "id": "body",
                    "primitive": "cylinder",
                    "operation": "base",
                    "parameters": {"radius": 30, "height": 100},
                },
                {
                    "id": "hollow",
                    "primitive": "cylinder",
                    "operation": "cut",
                    "parameters": {"radius": 25, "height": 90},
                },
                {
                    "id": "cap_main",
                    "primitive": "cylinder",
                    "operation": "union",
                    "parameters": {"radius": 20, "height": 15},
                },
            ],
        }
    )
    assert has_union_after_cavity(plan)


def test_open_vessel_violations_reject_free_csg_bottle():
    plan = plan_from_dict(
        {
            "part_name": "water_bottle_with_cap",
            "steps": [
                {
                    "id": "bottle_body",
                    "primitive": "cylinder",
                    "operation": "base",
                    "parameters": {"radius": 35, "height": 180},
                },
                {
                    "id": "hollow",
                    "primitive": "cylinder",
                    "operation": "cut",
                    "parameters": {"radius": 30, "height": 170},
                },
            ],
        }
    )
    errs = open_vessel_violations(plan)
    assert errs
    assert any("hollow_cylinder" in e or "revolve" in e for e in errs)


def test_open_vessel_one_step_hollow_cylinder_is_legal():
    plan = plan_from_dict(open_vessel_template_plan())
    assert open_vessel_violations(plan) == []
    assert construction_errors_for_plan(plan, family="open_vessel") == []


def test_library_bound_rejects_unknown_params():
    with pytest.raises((ValidationError, ValueError), match="primitive_gap|unknown parameter"):
        accept_plan(
            {
                "part_name": "x",
                "steps": [
                    {
                        "id": "r",
                        "primitive": "ring",
                        "operation": "base",
                        "parameters": {"ring_radius": 10, "tube_radius": 2},
                    }
                ],
            }
        )


def test_library_bound_rejects_cap_union():
    with pytest.raises((ValidationError, ValueError), match="cap|construction_error"):
        LibraryBoundPrimitivePlan.model_validate(
            {
                "part_name": "b",
                "steps": [
                    {
                        "id": "body",
                        "primitive": "hollow_cylinder",
                        "operation": "base",
                        "parameters": {
                            "outer_radius": 35,
                            "inner_radius": 32,
                            "height": 100,
                        },
                    },
                    {
                        "id": "cap_main",
                        "primitive": "cylinder",
                        "operation": "union",
                        "parameters": {"radius": 20, "height": 10},
                    },
                ],
            }
        )


def test_library_bound_accepts_hollow_cylinder_vessel():
    plan = accept_plan(open_vessel_template_plan(part_name="bottle"))
    assert plan.part_name == "bottle"
    assert plan.steps[0].primitive == "hollow_cylinder"  # type: ignore[attr-defined]


def test_extract_vessel_dims_from_failed_csg():
    outer, height = extract_vessel_dims_from_plan(
        {
            "steps": [
                {
                    "operation": "base",
                    "parameters": {"radius": 40, "height": 200},
                }
            ]
        }
    )
    assert outer == 40.0
    assert height == 200.0
