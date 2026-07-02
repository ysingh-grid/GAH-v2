"""Tests for backend/designs/ — session store, HTTP routes, and WebSocket chat.

Most WebSocket branch tests patch expensive boundaries. The real-world
simulation test patches only the RLM/VLM model decisions and lets the backend
run the actual geometry loop so artifact evidence is produced.
"""

from __future__ import annotations

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

    with patch("backend.designs.runner.run_planner_turn") as mock_planner:
        mock_planner.return_value = _ask_user_output("What size?")
        with client.websocket_connect(f"/designs/{design_id}/chat") as ws:
            ws.send_json({"type": "ping"})  # ignored
            ws.send_json({"type": "message", "text": "make a box"})
            evt1 = ws.receive_json()  # thinking
            evt2 = ws.receive_json()  # ask_user
            # exit context → server gets WebSocketDisconnect, exits cleanly

    assert evt1["type"] == "thinking"
    assert evt2["type"] == "ask_user"


def test_ws_ask_user_flow(client):
    """Planner returns ask_user → client receives thinking then ask_user event."""
    design_id = client.post("/designs").json()["design_id"]

    with patch("backend.designs.runner.run_planner_turn") as mock_planner:
        mock_planner.return_value = _ask_user_output(
            "What material?", options=["steel", "aluminium"]
        )
        with client.websocket_connect(f"/designs/{design_id}/chat") as ws:
            ws.send_json({"type": "message", "text": "I need a bracket"})
            evt1 = ws.receive_json()  # thinking
            evt2 = ws.receive_json()  # ask_user

    assert evt1["type"] == "thinking"
    assert evt2["type"] == "ask_user"
    assert evt2["question"] == "What material?"
    assert "steel" in evt2["options"]


def test_ws_history_grows_after_ask_user(client):
    """History must record user message AND planner question after ask_user."""
    design_id = client.post("/designs").json()["design_id"]

    with patch("backend.designs.runner.run_planner_turn") as mock_planner:
        mock_planner.return_value = _ask_user_output("What width?")
        with client.websocket_connect(f"/designs/{design_id}/chat") as ws:
            ws.send_json({"type": "message", "text": "make a plate"})
            ws.receive_json()  # thinking
            ws.receive_json()  # ask_user

    session = design_store.get_session(design_id)
    roles = [h["role"] for h in session.history]
    assert "user" in roles
    assert "planner" in roles


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
    assert "generating" in types
    assert "success" in types

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
    trace_path = Path("outputs") / run_id / "trace.json"

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
        shutil.rmtree(Path("outputs") / run_id, ignore_errors=True)


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
def test_ws_plan_ready_needs_user_flow(mock_planner, mock_loop, client):
    """loop returns needs_user → needs_user event, session status = needs_user."""
    mock_planner.return_value = _plan_ready_output()
    mock_loop.return_value = _loop_result("needs_user", question="Which axis to extrude?")

    design_id = client.post("/designs").json()["design_id"]
    with client.websocket_connect(f"/designs/{design_id}/chat") as ws:
        ws.send_json({"type": "message", "text": "make a flange"})
        ws.receive_json()   # thinking
        ws.receive_json()   # generating
        nu_evt = ws.receive_json()  # needs_user

    assert nu_evt["type"] == "needs_user"
    assert "axis" in nu_evt["question"]

    session = design_store.get_session(design_id)
    assert session.status == "needs_user"


@patch("backend.designs.runner.run_planner_turn")
def test_ws_planner_exception_sends_error_event(mock_planner, client):
    """If planner raises, client receives error event (not a crash)."""
    mock_planner.side_effect = RuntimeError("Gemini unavailable")

    design_id = client.post("/designs").json()["design_id"]
    with client.websocket_connect(f"/designs/{design_id}/chat") as ws:
        ws.send_json({"type": "message", "text": "make anything"})
        ws.receive_json()         # thinking
        err = ws.receive_json()   # error

    assert err["type"] == "error"
    assert "Gemini" in err["message"]


# ── Helpers (build typed return values for mocks) ────────────────────────────

def _ask_user_output(question: str, options: list[str] | None = None):
    from runtime.planner import PlannerOutput
    return PlannerOutput(
        action="ask_user",
        question=question,
        suggested_options=options or [],
    )


def _plan_ready_output(plan=None):
    from runtime.planner import PlannerOutput
    from runtime.schema import Operation, PrimitivePlan, PrimitiveStep
    plan = plan or PrimitivePlan(
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
    return PlannerOutput(action="plan_ready", plan=plan)


def _loop_result(
    status: str,
    category: str | None = None,
    question: str | None = None,
) -> MagicMock:
    from runtime.loop import LoopResult
    return LoopResult(
        status=status,
        run_id="test_run_001",
        trace_path="/tmp/trace.json",  # noqa: S108
        attempts=1,
        final_plan={"part_name": "box_test", "steps": []},
        failure_category=category,
        message=f"loop {status}",
        question=question,
    )


def _intake_ready() -> IntakeOutcome:
    return IntakeOutcome(status="ready", intake_context="")
