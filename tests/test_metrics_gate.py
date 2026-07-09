"""Host metric / hollow intent gates — no LLM."""

from __future__ import annotations

from runtime.metrics_gate import (
    MeasuredMetrics,
    TargetMetrics,
    check_envelope,
    check_hollow_intent,
    extract_target_metrics,
    measured_from_execution,
    plan_has_cavity_strategy,
)
from runtime.schema import plan_from_dict


def test_extract_z_span_from_to_z_anchor():
    prompt = (
        "base flange by 3mm along +Z. loft at Z=3 morphs at Z=53. "
        "neck to Z=63 to form a cylindrical neck, open and hollow"
    )
    t = extract_target_metrics(prompt)
    assert t.z_span == 63.0
    assert t.requires_hollow is True


def test_extract_no_hollow_when_not_stated():
    t = extract_target_metrics("design a 60mm cube")
    assert t.requires_hollow is False


def test_check_envelope_flags_short_height():
    measured = MeasuredMetrics(z_span=48.0, x_span=70.0, y_span=50.0, volume_mm3=90000.0)
    target = TargetMetrics(z_span=63.0, requires_hollow=False)
    err = check_envelope(measured, target)
    assert err is not None
    assert "dimensional_mismatch" in err
    assert "48" in err and "63" in err


def test_check_envelope_passes_within_tol():
    measured = MeasuredMetrics(z_span=62.5, x_span=70.0, y_span=50.0)
    target = TargetMetrics(z_span=63.0)
    assert check_envelope(measured, target) is None


def test_hollow_missing_when_requested_but_solid_plan():
    plan = plan_from_dict(
        {
            "part_name": "adapter",
            "steps": [
                {
                    "id": "body",
                    "primitive": "box",
                    "operation": "base",
                    "parameters": {"length": 70, "width": 50, "height": 3},
                }
            ],
        }
    )
    assert plan_has_cavity_strategy(plan) is False
    err = check_hollow_intent(plan, TargetMetrics(requires_hollow=True))
    assert err is not None
    assert "hollow_missing" in err


def test_hollow_ok_when_plan_has_cut():
    plan = plan_from_dict(
        {
            "part_name": "adapter",
            "steps": [
                {
                    "id": "body",
                    "primitive": "box",
                    "operation": "base",
                    "parameters": {"length": 70, "width": 50, "height": 30},
                },
                {
                    "id": "cavity",
                    "primitive": "box",
                    "operation": "cut",
                    "parameters": {"length": 50, "width": 30, "height": 28},
                },
            ],
        }
    )
    assert plan_has_cavity_strategy(plan) is True
    assert check_hollow_intent(plan, TargetMetrics(requires_hollow=True)) is None


def test_measured_from_execution():
    m = measured_from_execution(
        {
            "success": True,
            "volume": 100.0,
            "bbox": {
                "xmin": 0,
                "xmax": 10,
                "ymin": 0,
                "ymax": 20,
                "zmin": 0,
                "zmax": 63,
            },
        }
    )
    assert m is not None
    assert m.z_span == 63.0
    assert m.x_span == 10.0
    assert m.y_span == 20.0
