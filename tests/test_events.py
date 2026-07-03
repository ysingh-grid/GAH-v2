"""Unit tests for normalized run timeline events."""

from __future__ import annotations

import json
import shutil

from runtime.events import append_event, ingest_rlm_log, list_events
from tools.artifacts import new_run_id, run_dir


def test_append_event_persists_normalized_event():
    run_id = new_run_id("test_events")
    try:
        event = append_event(
            run_id,
            source="runtime",
            stage="compile",
            status="ok",
            title="Compiled CadQuery",
            summary="Plan compiled into Python.",
            payload={"faces": 6},
            artifact_refs={"code": "solid.py"},
        )

        loaded = list_events(run_id)
        assert loaded == [event]
        assert loaded[0]["run_id"] == run_id
        assert loaded[0]["source"] == "runtime"
        assert loaded[0]["artifact_refs"] == {"code": "solid.py"}
    finally:
        shutil.rmtree(run_dir(run_id), ignore_errors=True)


def test_ingest_rlm_log_summarizes_steps_and_truncates_large_output():
    run_id = new_run_id("test_events_rlm")
    log_path = run_dir(run_id) / "rlm.jsonl"
    long_output = "x" * 9000
    try:
        rows = [
            {"event_type": "agent_start", "depth": 0},
            {
                "event_type": "execution_result",
                "step": 1,
                "code": "print('hello')",
                "output": long_output,
                "hasError": False,
            },
            {"event_type": "final_result", "result": {"part_name": "box"}},
        ]
        log_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

        ingested = ingest_rlm_log(run_id, str(log_path), stage="planning")
        events = list_events(run_id)

        assert len(ingested) == 4
        assert events[0]["title"] == "RLM log captured"
        assert events[1]["title"] == "RLM agent started"
        assert events[2]["payload"]["output_truncated"] is True
        assert len(events[2]["payload"]["output"]) < len(long_output)
        assert events[3]["title"] == "RLM final result"
    finally:
        shutil.rmtree(run_dir(run_id), ignore_errors=True)
