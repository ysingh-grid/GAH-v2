"""Tests for backend/designs/ — session store, HTTP routes, and WebSocket chat.

Most WebSocket branch tests patch expensive boundaries. The real-world
simulation test patches only the RLM/VLM model decisions and lets the backend
run the actual geometry loop so artifact evidence is produced.
"""

from __future__ import annotations

import asyncio
import shutil
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from backend.app import create_app
from backend.designs import store as design_store
from backend.designs.intake import IntakeOutcome, IntakeState
from backend.designs.models import new_session
from tests.real_world_scenarios import mounting_plate_with_four_holes

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_store():
    """Wipe the in-memory session store before every test."""
    design_store._clear_for_testing()
    yield
    design_store._clear_for_testing()


@pytest.fixture(autouse=True)
def _default_intake_passthrough():
    """Keep the legacy websocket tests focused on the planner unless they override intake."""
    with patch("backend.designs.runner.run_intake_turn", return_value=_intake_ready()):
        yield


@pytest.fixture()
def client():
    return TestClient(create_app())


# ── Store unit tests ──────────────────────────────────────────────────────────

def test_new_session_defaults():
    s = new_session()
    assert s.status == "chatting"
    assert s.original_prompt == ""
    assert s.history == []
    assert s.id  # non-empty hex string


def test_create_session_registers_in_store():
    s = design_store.create_session()
    retrieved = design_store.get_session(s.id)
    assert retrieved is s


def test_create_multiple_sessions_unique_ids():
    ids = {design_store.create_session().id for _ in range(5)}
    assert len(ids) == 5


def test_get_session_missing_raises():
    with pytest.raises(KeyError, match="not found"):
        design_store.get_session("nonexistent")


def test_session_to_dict_fields():
    s = design_store.create_session()
    d = s.to_dict()
    assert d["id"] == s.id
    assert d["status"] == "chatting"
    assert d["original_prompt"] == ""
    assert d["history"] == []
    assert d["intake_state"] is None
    assert d["intake_context"] == ""
    assert d["run_id"] is None
    assert "forge_js" not in d  # forge path removed in the scope reduction


# ── HTTP route tests ──────────────────────────────────────────────────────────

def test_post_designs_returns_201_with_id(client):
    resp = client.post("/designs")
    assert resp.status_code == 201
    body = resp.json()
    assert "design_id" in body
    assert body["design_id"]  # non-empty


def test_get_design_returns_chatting(client):
    post = client.post("/designs")
    design_id = post.json()["design_id"]

    resp = client.get(f"/designs/{design_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == design_id
    assert body["status"] == "chatting"


def test_get_design_unknown_returns_404(client):
    resp = client.get("/designs/does_not_exist")
    assert resp.status_code == 404


def test_post_designs_creates_retrievable_session(client):
    design_id = client.post("/designs").json()["design_id"]
    # Verify store has the session directly.
    session = design_store.get_session(design_id)
    assert session.id == design_id


def test_list_runs_includes_artifact_folder_without_trace(client, tmp_path, monkeypatch):
    """Crashed runs can leave STL/STEP/render artifacts before trace writing."""
    from backend.designs import routes

    artifacts_dir = tmp_path / "artifacts"
    run_dir = artifacts_dir / "crashed_run"
    run_dir.mkdir(parents=True)
    (run_dir / "solid.stl").write_text("stl", encoding="utf-8")
    (run_dir / "solid.step").write_text("step", encoding="utf-8")
    (run_dir / "threeview.png").write_bytes(b"png")
    monkeypatch.setattr(routes, "_OUTPUTS_DIR", artifacts_dir)

    resp = client.get("/runs")

    assert resp.status_code == 200
    run = next(item for item in resp.json() if item["run_id"] == "crashed_run")
    assert run["status"] == "incomplete"
    assert run["has_trace"] is False
    assert run["has_stl"] is True
    assert run["has_step"] is True


def test_get_run_events_returns_normalized_timeline(client):
    from runtime.events import append_event
    from tools.artifacts import new_run_id, run_dir

    run_id = new_run_id("test_route_events")
    try:
        append_event(
            run_id,
            source="backend",
            stage="planning",
            status="running",
            title="Planning started",
        )

        resp = client.get(f"/runs/{run_id}/events")

        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"] == run_id
        assert body["events"][0]["title"] == "Planning started"
    finally:
        shutil.rmtree(run_dir(run_id), ignore_errors=True)


def test_get_run_artifacts_reports_available_outputs(client):
    from tools.artifacts import new_run_id, run_dir

    run_id = new_run_id("test_route_artifacts")
    base = run_dir(run_id)
    try:
        (base / "solid.stl").write_text("stl", encoding="utf-8")
        (base / "events.jsonl").write_text("", encoding="utf-8")

        resp = client.get(f"/runs/{run_id}/artifacts")

        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"] == run_id
        assert body["has_stl"] is True
        assert body["has_events"] is True
        assert body["has_trace"] is False
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ── WebSocket tests ───────────────────────────────────────────────────────────

def _collect_ws_events(ws_session, max_events: int = 20) -> list[dict]:
    """Drain events from the TestClient WS session until close or max."""
    events = []
    try:
        for _ in range(max_events):
            events.append(ws_session.receive_json())
    except Exception:  # noqa: S110, BLE001
        pass
    return events


def test_ws_unknown_design_sends_error(client):
    with client.websocket_connect("/designs/bad_id/chat") as ws:
        events = _collect_ws_events(ws, max_events=5)
    assert any(e["type"] == "error" for e in events)


def test_ws_non_message_event_ignored(client):
    """Sending an event with type != 'message' should not crash the handler."""
    design_id = client.post("/designs").json()["design_id"]

    with (
        patch("backend.designs.runner.run_planner_turn") as mock_planner,
        patch("backend.designs.runner.run_geometry_loop") as mock_loop,
    ):
        mock_planner.return_value = _plan_ready_output()
        mock_loop.return_value = _loop_result("success")
        with client.websocket_connect(f"/designs/{design_id}/chat") as ws:
            ws.send_json({"type": "ping"})  # ignored
            ws.send_json({"type": "message", "text": "make a box"})
            events = _collect_ws_events(ws)
            # exit context → server gets WebSocketDisconnect, exits cleanly

    types = [event["type"] for event in events]
    assert "thinking" in types
    assert "trace_event" in types
    assert "plan" in types
    assert "generating" in types


def test_ws_image_attachment_hits_intake_before_planner(client):
    """An image attachment should go through intake first, before planner runs."""
    design_id = client.post("/designs").json()["design_id"]
    captured: dict[str, list] = {}

    def fake_intake(*, session, user_text, attachments):  # noqa: ANN001
        captured["attachments"] = attachments
        return IntakeOutcome(
            status="need_user",
            question="How large should the bracket be?",
            state=IntakeState(
                source="image",
                visual_summary="A bracket-like shape.",
                question_queue=["How large should the bracket be?"],
                attachment_names=[str(attachment.get("filename")) for attachment in attachments],
            ),
        )

    with (
        patch("backend.designs.runner.run_intake_turn", side_effect=fake_intake),
        patch("backend.designs.runner.run_planner_turn") as mock_planner,
    ):
        mock_planner.side_effect = AssertionError("planner should not run before intake finishes")
        with client.websocket_connect(f"/designs/{design_id}/chat") as ws:
            ws.send_json(
                {
                    "type": "message",
                    "text": "make this",
                    "attachments": [
                        {
                            "filename": "reference.png",
                            "mime_type": "image/png",
                            "data": "ZmFrZQ==",
                        }
                    ],
                }
            )
            evt1 = ws.receive_json()  # thinking
            evt2 = ws.receive_json()  # ask_user

    assert evt1["type"] == "thinking"
    assert evt2["type"] == "ask_user"
    assert captured["attachments"][0]["filename"] == "reference.png"


@patch("backend.designs.runner.write_stl_to_studio", return_value=True)
@patch("backend.designs.runner.run_geometry_loop")
@patch("backend.designs.runner.run_planner_turn")
def test_ws_plan_ready_success_flow(mock_planner, mock_loop, mock_write_stl, client):
    """plan_ready → loop success → success event (run_id + plan); STL pushed to Studio."""
    mock_planner.return_value = _plan_ready_output()
    mock_loop.return_value = _loop_result("success")

    design_id = client.post("/designs").json()["design_id"]
    with client.websocket_connect(f"/designs/{design_id}/chat") as ws:
        ws.send_json({"type": "message", "text": "10mm box"})
        events = _collect_ws_events(ws)

    types = [e["type"] for e in events]
    assert "thinking" in types
    assert "trace_event" in types
    assert "generating" in types
    assert "success" in types

    trace_events = [e["event"] for e in events if e["type"] == "trace_event"]
    assert any(event["stage"] == "planning" for event in trace_events)
    assert any(event["stage"] == "outcome" for event in trace_events)

    success_evt = next(e for e in events if e["type"] == "success")
    assert "forge_js" not in success_evt
    assert success_evt["run_id"]
    assert "plan" in success_evt

    session = design_store.get_session(design_id)
    assert session.status == "done"
    mock_write_stl.assert_called_once()  # STL copied into the Studio workspace


@patch("backend.designs.runner.run_planner_turn")
def test_ws_plan_ready_runs_real_geometry_pipeline_with_mocked_models(mock_planner, client):
    """plan_ready -> real geometry loop -> trace/render artifacts -> success event."""
    pytest.importorskip("cadquery")
    pytest.importorskip("meshlib.mrmeshpy")
    pytest.importorskip("vtk")

    import json
    import shutil
    from pathlib import Path

    scenario = mounting_plate_with_four_holes()
    mock_planner.return_value = _plan_ready_output(scenario.plan)

    def fake_render(_stl_path: str, run_id: str) -> dict:
        from tools.artifacts import run_dir

        png_path = run_dir(run_id) / "threeview.png"
        png_path.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe"
            b"\x02\xfeA\xe2!\xbc\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return {
            "success": True,
            "png_path": str(png_path),
            "width": 1,
            "height": 1,
            "views": ["stub"],
            "renders": {"composite": str(png_path)},
        }

    with (
        patch("tools.render_views.render_views", side_effect=fake_render),
        patch("tools.verify_geometry.verify_geometry") as judge,
    ):
        judge.return_value = {
            "passed": True,
            "feedback": "All constraints met.",
            "render_png": "",
        }

        design_id = client.post("/designs").json()["design_id"]
        with client.websocket_connect(f"/designs/{design_id}/chat") as ws:
            ws.send_json({"type": "message", "text": scenario.prompt})
            events = _collect_ws_events(ws)

    success_evt = next(e for e in events if e["type"] == "success")
    run_id = success_evt["run_id"]
    trace_path = Path("artifacts") / run_id / "trace.json"

    try:
        assert success_evt["run_id"]
        assert success_evt["plan"]["part_name"] == "electronics_mounting_plate"
        assert trace_path.exists()

        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        assert trace["outcome"]["status"] == "success"
        assert trace["verdict"]["passed"] is True
        assert Path(trace["execution_result"]["step_path"]).exists()
        assert Path(trace["execution_result"]["stl_path"]).exists()
        assert Path(trace["renders"]["png_path"]).exists()

        session = design_store.get_session(design_id)
        assert session.status == "done"
        assert session.run_id == run_id
    finally:
        shutil.rmtree(Path("artifacts") / run_id, ignore_errors=True)


@patch("backend.designs.runner.run_geometry_loop")
@patch("backend.designs.runner.run_planner_turn")
def test_ws_plan_ready_failed_flow(mock_planner, mock_loop, client):
    """plan_ready → loop failed → failed event, session status = failed."""
    mock_planner.return_value = _plan_ready_output()
    mock_loop.return_value = _loop_result("failed", category="geometry_invalid")

    design_id = client.post("/designs").json()["design_id"]
    with client.websocket_connect(f"/designs/{design_id}/chat") as ws:
        ws.send_json({"type": "message", "text": "make something impossible"})
        events = _collect_ws_events(ws)

    types = [e["type"] for e in events]
    assert "failed" in types

    session = design_store.get_session(design_id)
    assert session.status == "failed"


@patch("backend.designs.runner.run_geometry_loop")
@patch("backend.designs.runner.run_planner_turn")
def test_ws_plan_ready_replan_failure_flow(mock_planner, mock_loop, client):
    """loop can no longer escalate to needs_user — a replan failure is just 'failed'."""
    mock_planner.return_value = _plan_ready_output()
    mock_loop.return_value = _loop_result(
        "failed",
        category="geometry_invalidity",
        message="replanner failed to produce a corrected plan",
    )

    design_id = client.post("/designs").json()["design_id"]
    with client.websocket_connect(f"/designs/{design_id}/chat") as ws:
        ws.send_json({"type": "message", "text": "make a flange"})
        events = _collect_ws_events(ws)

    types = [e["type"] for e in events]
    assert "failed" in types
    assert "needs_user" not in types

    session = design_store.get_session(design_id)
    assert session.status == "failed"


@patch("backend.designs.runner.run_planner_turn")
def test_ws_planner_exception_sends_error_event(mock_planner, client):
    """If planner raises, client receives error event (not a crash)."""
    mock_planner.side_effect = RuntimeError("Gemini unavailable")

    design_id = client.post("/designs").json()["design_id"]
    with client.websocket_connect(f"/designs/{design_id}/chat") as ws:
        ws.send_json({"type": "message", "text": "make anything"})
        events = [ws.receive_json() for _ in range(4)]

    err = next(event for event in events if event["type"] == "error")
    assert err["type"] == "error"
    assert "Gemini" in err["message"]
    assert any(event["type"] == "trace_event" for event in events)


def test_temporal_result_exception_includes_run_id(monkeypatch):
    """Unexpected Temporal workflow failures should be connectable to artifacts."""
    from backend.designs import runner

    events: list[dict] = []
    session = new_session()
    session.original_prompt = "make a cube"

    class FakeHandle:
        async def result(self):
            raise RuntimeError("Workflow execution failed")

        async def query(self, _query):
            return "verifying"

    class FakeClient:
        async def start_workflow(self, *_args, **_kwargs):
            return FakeHandle()

    async def fake_get_client():
        return FakeClient()

    async def send(event: dict) -> None:
        events.append(event)

    monkeypatch.setattr("temporal.client.get_client", fake_get_client)

    asyncio.run(
        runner._run_via_temporal(
            session,
            _plan_ready_output(),
            "run_123",
            send,
            backend_url="http://localhost:8001",
            planner_history=[],
            last_event_seq=0,
        )
    )

    assert session.status == "failed"
    assert events[-1]["type"] == "error"
    assert "run_123" in events[-1]["message"]
    assert "Workflow execution failed" in events[-1]["message"]


# ── Helpers (build typed return values for mocks) ────────────────────────────

def _plan_ready_output(plan=None):
    from runtime.schema import Operation, PrimitivePlan, PrimitiveStep
    return plan or PrimitivePlan(
        part_name="box_test",
        steps=[
            PrimitiveStep(
                id="base",
                primitive="box",
                operation=Operation.base,
                parameters={"length": 10.0, "width": 10.0, "height": 10.0},
            )
        ],
    )


def _loop_result(
    status: str,
    category: str | None = None,
    message: str | None = None,
) -> MagicMock:
    from runtime.loop import LoopResult
    return LoopResult(
        status=status,
        run_id="test_run_001",
        trace_path="/tmp/trace.json",  # noqa: S108
        attempts=1,
        final_plan={"part_name": "box_test", "steps": []},
        failure_category=category,
        message=message or f"loop {status}",
    )


def _intake_ready() -> IntakeOutcome:
    return IntakeOutcome(status="ready", intake_context="")


# ── /config endpoint ──────────────────────────────────────────────────────────

def test_config_endpoint_returns_200(client):
    resp = client.get("/config")
    assert resp.status_code == 200


def test_config_endpoint_has_forgecad_studio_url_key(client):
    body = client.get("/config").json()
    assert "forgecad_studio_url" in body


def test_config_endpoint_has_backend_url_key(client):
    body = client.get("/config").json()
    assert "backend_url" in body


def test_config_endpoint_forgecad_url_from_env(client, monkeypatch):
    monkeypatch.setenv("FORGECAD_STUDIO_URL", "http://studio.test:4000")
    body = client.get("/config").json()
    assert body["forgecad_studio_url"] == "http://studio.test:4000"


def test_config_endpoint_empty_when_unset(client, monkeypatch):
    monkeypatch.delenv("FORGECAD_STUDIO_URL", raising=False)
    body = client.get("/config").json()
    assert body["forgecad_studio_url"] == ""


def test_rlm_list_primitives_endpoint_matches_pull_tool_contract(client):
    """RLM pull_tools.list_primitives calls /internal/list-primitives."""
    resp = client.get("/internal/list-primitives")

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict)
    assert "box" in body


def test_rlm_lookup_primitive_endpoint_matches_pull_tool_contract(client):
    """RLM pull_tools.lookup_primitive calls /internal/lookup-primitive."""
    resp = client.get("/internal/lookup-primitive", params={"key": "box"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "box"
    assert "parameters" in body


def test_system_status_reports_runtime_dependencies(client, monkeypatch):
    from backend.services import system_diagnostics

    monkeypatch.setattr(system_diagnostics, "temporal_status", lambda: {
        "cli": True,
        "server_up": True,
        "managed_worker_up": False,
        "worker_up": False,
        "worker_exit_code": 1,
        "last_worker_errors": ["TypeError: verify_geometry"],
    })
    monkeypatch.setattr(system_diagnostics.shutil, "which", lambda name: f"/bin/{name}")

    resp = client.get("/system/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["backend"]["status"] == "ok"
    assert body["temporal"]["server_up"] is True
    assert body["temporal"]["managed_worker_up"] is False
    assert body["tools"]["forgecad_cli"] == "/bin/forgecad"
    assert body["tools"]["mypy"] == "/bin/mypy"
    assert "TypeError: verify_geometry" in body["temporal"]["last_worker_errors"]


def test_system_logs_returns_safe_tail_for_known_log(client, tmp_path, monkeypatch):
    from backend.services import system_diagnostics

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "temporal_worker.log").write_text("one\ntwo\nthree\n", encoding="utf-8")
    monkeypatch.setattr(system_diagnostics, "LOGS", log_dir)

    resp = client.get("/system/logs", params={"service": "temporal_worker", "tail": 2})

    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "temporal_worker"
    assert body["lines"] == ["two", "three"]


def test_system_logs_rejects_unknown_service(client):
    resp = client.get("/system/logs", params={"service": "../secret"})

    assert resp.status_code == 404
