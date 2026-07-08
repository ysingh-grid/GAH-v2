"""Tests for the design action endpoints: POST /designs/{id}/cancel and /handoff.

Cancel: Temporal path cancels the workflow (id == run_id) cleanly; in-process
path is best-effort (sets a flag). Handoff: re-renders the run's STL into the
ForgeCAD Studio workspace, gated on a successful run.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from backend.app import create_app
from backend.designs import store


@pytest.fixture()
def client():
    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _reset_store():
    store._clear_for_testing()
    yield
    store._clear_for_testing()


# ── Cancel ────────────────────────────────────────────────────────────────────


def test_cancel_unknown_design_returns_404(client):
    resp = client.post("/designs/nope/cancel")
    assert resp.status_code == 404


def test_cancel_in_process_sets_flag_and_status(client, monkeypatch):
    monkeypatch.setattr("backend.designs.runner._USE_TEMPORAL", False)
    session = store.create_session()
    session.status = "generating"
    session.run_id = "run_abc"

    resp = client.post(f"/designs/{session.id}/cancel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cancelled"
    assert body["workflow_cancelled"] is False
    assert session.cancelled is True
    assert session.status == "cancelled"


def test_cancel_temporal_path_cancels_workflow(client, monkeypatch):
    monkeypatch.setattr("backend.designs.runner._USE_TEMPORAL", True)

    cancelled = {"called_with": None}

    class _FakeHandle:
        def __init__(self, wf_id: str) -> None:
            self._wf_id = wf_id

        async def cancel(self) -> None:
            cancelled["called_with"] = self._wf_id

    class _FakeClient:
        def get_workflow_handle(self, wf_id: str) -> _FakeHandle:
            return _FakeHandle(wf_id)

    async def _fake_get_client():
        return _FakeClient()

    monkeypatch.setattr("temporal.client.get_client", _fake_get_client)

    session = store.create_session()
    session.status = "generating"
    session.run_id = "run_xyz"

    resp = client.post(f"/designs/{session.id}/cancel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cancelled"
    assert body["workflow_cancelled"] is True
    assert cancelled["called_with"] == "run_xyz"


# ── Handoff ───────────────────────────────────────────────────────────────────


def test_handoff_unknown_design_returns_404(client):
    resp = client.post("/designs/nope/handoff")
    assert resp.status_code == 404


def test_handoff_before_success_returns_400(client):
    session = store.create_session()
    session.status = "generating"  # no successful run yet
    resp = client.post(f"/designs/{session.id}/handoff")
    assert resp.status_code == 400


def test_handoff_after_success_writes_studio_files(client, monkeypatch):
    calls = {"run_id": None}

    def _fake_write(run_id: str) -> bool:
        calls["run_id"] = run_id
        return True

    monkeypatch.setattr("backend.designs.routes.write_stl_to_studio", _fake_write)

    session = store.create_session()
    session.status = "done"
    session.run_id = "run_done"

    resp = client.post(f"/designs/{session.id}/handoff")
    assert resp.status_code == 200
    assert resp.json()["run_id"] == "run_done"
    assert calls["run_id"] == "run_done"
