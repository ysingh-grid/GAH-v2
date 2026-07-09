"""Temporal path must run the same host hollow + gates as runtime.loop.

Regression: design_9ef3073f solid-only adapter "succeeded" because Temporal used
split compile/execute without auto_hollow or host hollow gates. VLM only saw the
outer silhouette.
"""

from __future__ import annotations

from runtime.schema import plan_from_dict, plan_to_dict
from temporal.activities import auto_hollow_activity, host_gates_activity
from temporal.shared import AutoHollowInput, HostGatesInput


def _solid_adapter_plan_dict() -> dict:
    return plan_to_dict(
        plan_from_dict(
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
    )


def test_host_gates_fail_solid_adapter_without_cavity():
    """Structural through-path + solid plan → hollow_missing (no VLM involved)."""
    plan_dict = _solid_adapter_plan_dict()
    # Fake solid execution (volume ~ solid fill) — gates only need bbox/volume.
    execution = {
        "success": True,
        "volume": 91482.0,
        "bbox": {
            "xmin": -35,
            "xmax": 35,
            "ymin": -25,
            "ymax": 25,
            "zmin": 0,
            "zmax": 63,
        },
        "num_solids": 1,
        "num_shells": 1,
    }
    prompt = (
        "Design a 3D transition adapter with 70x50 flange, loft to 30mm circle, "
        "neck to Z=63."
    )
    out = host_gates_activity(
        HostGatesInput(
            prompt=prompt,
            plan_dict=plan_dict,
            execution_result=execution,
            feature_checklist="",
            through_path="",
        )
    )
    assert out.ok is False
    assert out.failure_stage == "hollow_missing"
    assert "hollow" in out.failure_detail.lower() or "cavity" in out.failure_detail.lower()


def test_auto_hollow_activity_adds_cavity_and_lowers_volume():
    """End-to-end host auto-hollow activity on the 9ef3073f solid plan."""
    import shutil

    import pytest

    pytest.importorskip("cadquery")
    from runtime.compile_cadquery import compile_plan_to_cadquery
    from runtime.schema import load_library
    from tools.artifacts import new_run_id, run_dir
    from tools.execute_cadquery import execute_cadquery

    plan_dict = _solid_adapter_plan_dict()
    code = compile_plan_to_cadquery(plan_from_dict(plan_dict), load_library())
    rid = new_run_id("test_temporal_auto_hollow")
    try:
        solid = execute_cadquery(code, rid)
        assert solid.get("success") is True, solid.get("error")
        solid_vol = float(solid["volume"])
        assert solid_vol > 80000

        out = auto_hollow_activity(
            AutoHollowInput(
                plan_dict=plan_dict,
                run_id=rid,
                prompt="transition adapter loft neck Z=63",
                feature_checklist="",
                through_path="",
                execution_result=solid,
                code=code,
            )
        )
        assert out.ok is True, out.failure_detail
        assert out.applied is True
        steps = out.plan_dict.get("steps") or []
        ops = [s.get("operation") for s in steps if isinstance(s, dict)]
        assert "cut" in ops
        hollow_vol = float((out.execution_result or {}).get("volume") or 0)
        assert hollow_vol < 0.85 * solid_vol
        assert hollow_vol < 40000
        assert (out.execution_result or {}).get("num_solids") == 1
    finally:
        shutil.rmtree(run_dir(rid), ignore_errors=True)
