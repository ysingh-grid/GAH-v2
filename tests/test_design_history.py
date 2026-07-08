"""Unit tests for the 'Previous Run' reader (backend/designs/history.py).

The reader scans the on-disk artifact store (outputs/{run_id}/trace.json) and
returns compact, newest-first run summaries for the UI's run picker.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.designs.history import list_previous_runs


def _write_trace(
    outputs_dir: Path, run_id: str, *, timestamp: str, prompt: str, status: str
) -> None:
    """Persist a minimal trace.json under outputs_dir/run_id/ like the real writer does."""
    run_folder = outputs_dir / run_id
    run_folder.mkdir(parents=True, exist_ok=True)
    trace = {
        "run_id": run_id,
        "timestamp": timestamp,
        "prompt": prompt,
        "plan": {"part_name": "widget", "steps": []},
        "outcome": {"status": status, "failure_category": None},
    }
    (run_folder / "trace.json").write_text(json.dumps(trace), encoding="utf-8")


def test_list_previous_runs_on_empty_dir_returns_empty(tmp_path: Path) -> None:
    assert list_previous_runs(outputs_dir=tmp_path) == []


def test_list_previous_runs_on_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert list_previous_runs(outputs_dir=tmp_path / "does_not_exist") == []


def test_list_previous_runs_returns_summary_fields(tmp_path: Path) -> None:
    _write_trace(
        tmp_path,
        "design_aaa_20260101-000000_0001",
        timestamp="2026-01-01T00:00:00+00:00",
        prompt="A mounting bracket\nwith 4 holes",
        status="success",
    )
    runs = list_previous_runs(outputs_dir=tmp_path)
    assert len(runs) == 1
    run = runs[0]
    assert run["run_id"] == "design_aaa_20260101-000000_0001"
    assert run["status"] == "success"
    assert run["part_name"] == "widget"
    # Prompt is collapsed to its first line, so the picker stays compact.
    assert run["prompt"] == "A mounting bracket"


def test_list_previous_runs_sorted_newest_first(tmp_path: Path) -> None:
    _write_trace(
        tmp_path, "run_old", timestamp="2026-01-01T00:00:00+00:00", prompt="old", status="success"
    )
    _write_trace(
        tmp_path, "run_new", timestamp="2026-06-01T00:00:00+00:00", prompt="new", status="failed"
    )
    runs = list_previous_runs(outputs_dir=tmp_path)
    assert [r["run_id"] for r in runs] == ["run_new", "run_old"]


def test_list_previous_runs_skips_malformed_trace(tmp_path: Path) -> None:
    good = tmp_path / "good"
    good.mkdir()
    (good / "trace.json").write_text(
        json.dumps(
            {
                "run_id": "good",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "outcome": {"status": "success"},
            }
        ),
        encoding="utf-8",
    )
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "trace.json").write_text("{not valid json", encoding="utf-8")
    runs = list_previous_runs(outputs_dir=tmp_path)
    assert [r["run_id"] for r in runs] == ["good"]


def test_get_designs_route_returns_list() -> None:
    """GET /designs returns a JSON array (the run picker's data source)."""
    from starlette.testclient import TestClient

    from backend.app import create_app

    client = TestClient(create_app())
    resp = client.get("/designs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
