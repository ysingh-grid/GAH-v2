"""Unit tests for runtime/trace.py — the 6-category failure taxonomy + writing."""

import json
import shutil

import pytest

from runtime.trace import (
    FailureCategory,
    build_trace,
    category_for_stage,
    write_trace,
)


def test_six_failure_categories_exist():
    assert {c.value for c in FailureCategory} == {
        "primitive_gap",
        "geometry_invalidity",
        "visual_mismatch",
        "translation_drift",
        "verifier_miss",
        "user_ambiguity",
    }


def test_category_for_stage_maps_known_stages():
    assert category_for_stage("cadquery_compile") is FailureCategory.geometry_invalidity
    assert category_for_stage("cadquery_execute") is FailureCategory.geometry_invalidity
    assert category_for_stage("mesh_repair") is FailureCategory.geometry_invalidity
    assert category_for_stage("visual_mismatch") is FailureCategory.visual_mismatch
    assert category_for_stage("primitive_gap") is FailureCategory.primitive_gap


def test_category_for_unknown_stage_defaults_to_geometry_invalidity():
    assert category_for_stage("???") is FailureCategory.geometry_invalidity


def _base_kwargs():
    return {
        "run_id": "x",
        "prompt": "p",
        "plan": {"part_name": "x"},
        "code": "result = None",
        "execution_result": None,
        "mesh_report": None,
        "renders": None,
        "verdict": None,
    }


def test_success_trace_needs_no_category():
    trace = build_trace(**_base_kwargs(), status="success", attempts=1, failure_category=None)
    assert trace["outcome"]["status"] == "success"
    assert trace["outcome"]["failure_category"] is None


def test_failed_trace_without_category_raises():
    with pytest.raises(ValueError, match="requires a failure_category"):
        build_trace(**_base_kwargs(), status="failed", attempts=2, failure_category=None)


def test_failed_trace_carries_category():
    trace = build_trace(
        **_base_kwargs(),
        status="failed",
        attempts=3,
        failure_category=FailureCategory.geometry_invalidity,
        failure_detail="bad solid",
    )
    assert trace["outcome"]["failure_category"] == "geometry_invalidity"
    assert trace["outcome"]["failure_detail"] == "bad solid"


def test_write_trace_persists_json():
    from tools.artifacts import new_run_id, run_dir

    run_id = new_run_id("test_trace")
    try:
        kwargs = _base_kwargs()
        kwargs["run_id"] = run_id
        trace = build_trace(**kwargs, status="success", attempts=1, failure_category=None)
        path = write_trace(trace)
        with open(path) as f:
            loaded = json.load(f)
        assert loaded["run_id"] == run_id
        assert loaded["outcome"]["status"] == "success"
    finally:
        shutil.rmtree(run_dir(run_id), ignore_errors=True)
