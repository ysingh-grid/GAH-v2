"""Unit tests for the trace-flywheel approved-designs store.

Every test redirects _APPROVED_PATH to a tmp_path so the real data/ store is
never touched.
"""

from __future__ import annotations

import json

import pytest

from backend.approved_store import store as astore


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(astore, "_APPROVED_PATH", tmp_path / "approved_designs.json")


def _plan(part="widget"):
    return {"part_name": part, "units": "mm",
            "steps": [{"id": "b", "primitive": "box", "operation": "base"}]}


def test_append_creates_file_and_entry():
    r = astore.append_approved(run_id="run_1", original_prompt="a small widget", plan=_plan())
    assert r["status"] == "approved"
    assert astore._APPROVED_PATH.exists()
    doc = json.loads(astore._APPROVED_PATH.read_text())
    assert len(doc["approved"]) == 1
    e = doc["approved"][0]
    assert e["run_id"] == "run_1"
    assert e["keywords"]  # derived, non-empty
    assert e["plan"]["part_name"] == "widget"


def test_append_idempotent_by_run_id():
    astore.append_approved(run_id="run_1", original_prompt="a widget", plan=_plan())
    r2 = astore.append_approved(run_id="run_1", original_prompt="different text", plan=_plan("other"))
    assert r2["status"] == "already_approved"
    assert len(astore._load()["approved"]) == 1


def test_append_skips_empty_plan():
    assert astore.append_approved(run_id="r", original_prompt="x", plan={})["status"] == "skipped"
    assert astore.append_approved(run_id="", original_prompt="x", plan=_plan())["status"] == "skipped"


def test_append_atomic_leaves_no_tmp():
    astore.append_approved(run_id="run_1", original_prompt="a widget", plan=_plan())
    assert not (astore._APPROVED_PATH.parent / (astore._APPROVED_PATH.name + ".tmp")).exists()


def test_corrupt_store_degrades_to_empty():
    astore._APPROVED_PATH.parent.mkdir(parents=True, exist_ok=True)
    astore._APPROVED_PATH.write_text('{"approved": [ this is not json')
    # readers never raise; a corrupt file looks like an empty store
    assert astore._load() == {"approved": []}
    assert astore.index_approved() == {}
    assert astore.fetch_approved(["approved__run_1"]) == {}


def test_index_newest_first_and_capped(monkeypatch):
    monkeypatch.setattr(astore, "MAX_INDEX", 2)
    for i in range(4):
        astore.append_approved(run_id=f"run_{i}", original_prompt=f"prompt {i}", plan=_plan(f"p{i}"))
    idx = astore.index_approved()
    assert list(idx.keys()) == ["approved__run_3", "approved__run_2"]  # newest first, capped
    assert idx["approved__run_3"] == "prompt 3"


def test_fetch_returns_only_requested_with_steps():
    astore.append_approved(run_id="run_1", original_prompt="a vase", plan=_plan("vase"))
    astore.append_approved(run_id="run_2", original_prompt="a bracket", plan=_plan("bracket"))
    out = astore.fetch_approved(["approved__run_1", "bolt_circle"])  # non-approved key ignored
    assert set(out) == {"approved__run_1"}
    assert out["approved__run_1"]["steps"] == _plan("vase")["steps"]
    assert "Approved past design" in out["approved__run_1"]["description"]


def test_near_dup_guard():
    p = "a hexagonal steel flange with six bolt holes"
    astore.append_approved(run_id="run_1", original_prompt=p, plan=_plan("flange"))
    r2 = astore.append_approved(run_id="run_2", original_prompt=p, plan=_plan("flange"))
    assert r2["status"] == "duplicate"
    assert len(astore._load()["approved"]) == 1


def test_max_approved_trims_oldest(monkeypatch):
    monkeypatch.setattr(astore, "MAX_APPROVED", 3)
    monkeypatch.setattr(astore, "_NEAR_DUP_KEYWORDS", 99)  # disable dup guard for distinct-ish parts
    for i in range(5):
        astore.append_approved(run_id=f"run_{i}", original_prompt=f"unique object number {i}", plan=_plan(f"p{i}"))
    entries = astore._load()["approved"]
    assert len(entries) == 3
    assert [e["run_id"] for e in entries] == ["run_2", "run_3", "run_4"]  # oldest dropped
