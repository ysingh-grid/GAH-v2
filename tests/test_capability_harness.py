"""Unit tests for the capability harness — no live model, all injected/stubbed."""

from __future__ import annotations

import json
from pathlib import Path

from eval.capability_harness import (
    CASES,
    CapabilityCase,
    CaseResult,
    run_suite,
    scan_existing_traces,
    summarize,
    to_markdown_table,
)


def _ok(case: CapabilityCase) -> CaseResult:
    return CaseResult(id=case.id, tier=case.tier, prompt=case.prompt, status="success", attempts=1)


def test_curated_set_covers_all_three_tiers_and_the_laptop_stand():
    tiers = {c.tier for c in CASES}
    assert {"t1", "t2", "t3"} <= tiers
    assert any("foldable laptop stand" in c.prompt for c in CASES)


def test_run_suite_records_success_failure_and_exception():
    def run_fn(case: CapabilityCase) -> CaseResult:
        if case.tier == "t3":
            raise RuntimeError("boom")  # a crash must be captured, not abort the suite
        if case.tier == "t2":
            return CaseResult(
                id=case.id, tier=case.tier, prompt=case.prompt,
                status="failed", failure_category="visual_mismatch", attempts=3,
            )
        return _ok(case)

    results = run_suite(CASES, run_fn)
    assert len(results) == len(CASES)
    statuses = {r.tier: r.status for r in results}
    assert statuses["t1"] == "success"
    assert statuses["t2"] == "failed"
    assert statuses["t3"] == "exception"  # the raising case became a recorded result


def test_summarize_computes_pass_rate_and_tier_and_category_tallies():
    results = [
        CaseResult("a", "t1", "p", "success", attempts=1),
        CaseResult("b", "t1", "p", "success", attempts=1),
        CaseResult("c", "t3", "p", "failed", failure_category="visual_mismatch", attempts=3),
    ]
    s = summarize(results)
    assert s["total"] == 3
    assert s["passed"] == 2
    assert s["pass_rate"] == round(2 / 3, 3)
    assert s["by_tier"]["t1"] == {"passed": 2, "total": 2}
    assert s["by_tier"]["t3"] == {"passed": 0, "total": 1}
    assert s["by_category"]["visual_mismatch"] == 1


def test_to_markdown_table_has_header_and_pass_rate_line():
    table = to_markdown_table([CaseResult("a", "t1", "p", "success", attempts=1)])
    assert "| id | tier | status |" in table
    assert "Pass rate: 1/1 (100%)" in table


def test_scan_existing_traces_reads_outcomes(tmp_path: Path):
    run_dir = tmp_path / "design_abc"
    run_dir.mkdir()
    (run_dir / "trace.json").write_text(
        json.dumps(
            {
                "run_id": "design_abc",
                "prompt": "make a widget\nsecond line",
                "outcome": {
                    "status": "failed",
                    "attempts": 3,
                    "failure_category": "visual_mismatch",
                    "failure_detail": "missing feature",
                },
            }
        ),
        encoding="utf-8",
    )
    results = scan_existing_traces(tmp_path)
    assert len(results) == 1
    r = results[0]
    assert r.status == "failed"
    assert r.failure_category == "visual_mismatch"
    assert r.attempts == 3
    assert r.prompt == "make a widget"  # first line only


def test_scan_existing_traces_empty_dir_is_safe(tmp_path: Path):
    assert scan_existing_traces(tmp_path / "does_not_exist") == []
