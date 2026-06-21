from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def assert_contract(payload, tool):
    assert payload["tool"] == tool
    assert "ok" in payload
    assert "data" in payload
    assert "error" in payload


def test_health():
    response = client.get("/internal/health")
    assert response.status_code == 200
    payload = response.json()
    assert_contract(payload, "health")
    assert payload["ok"] is True
    assert payload["data"]["status"] == "up"


def test_read_skill():
    response = client.post("/internal/read-skill", json={"skill_name": "intent_extraction"})
    assert response.status_code == 200
    payload = response.json()
    assert_contract(payload, "read_skill")
    assert payload["ok"] is True
    assert payload["data"]["path"] == "skills/intent_extraction.md"


def test_path_traversal_rejected():
    response = client.post("/internal/read-file", json={"path": "../../secret.txt"})
    payload = response.json()
    assert_contract(payload, "read_file")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "PATH_NOT_ALLOWED"


def test_write_file_allowed_path():
    response = client.post(
        "/internal/write-file",
        json={"path": "generated/test_backend_bridge.txt", "content": "hello\n", "overwrite": True},
    )
    payload = response.json()
    assert_contract(payload, "write_file")
    assert payload["ok"] is True
    assert payload["data"]["path"] == "generated/test_backend_bridge.txt"


def test_unknown_pipeline_rejected():
    response = client.post("/internal/run-pipeline", json={"pipeline_name": "shell", "args": {}})
    payload = response.json()
    assert_contract(payload, "run_pipeline")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "UNKNOWN_PIPELINE"


def test_execute_tool_list_and_lookup_primitives():
    list_response = client.post("/internal/execute-tool", json={"tool_name": "list_primitives", "payload": {}})
    list_payload = list_response.json()
    assert_contract(list_payload, "execute_tool")
    assert list_payload["ok"] is True
    assert "box" in list_payload["data"]["result"]["primitives"]

    lookup_response = client.post(
        "/internal/execute-tool",
        json={"tool_name": "lookup_primitive", "payload": {"name": "box"}},
    )
    lookup_payload = lookup_response.json()
    assert_contract(lookup_payload, "execute_tool")
    assert lookup_payload["ok"] is True
    assert lookup_payload["data"]["result"]["name"] == "box"


def test_all_project_tools_are_exposed():
    response = client.post("/internal/execute-tool", json={"tool_name": "list_project_tools", "payload": {}})
    payload = response.json()
    assert_contract(payload, "execute_tool")
    assert payload["ok"] is True
    exposed = set(payload["data"]["result"]["tools"])
    expected = {
        "read_skill",
        "list_skills",
        "lookup_primitive",
        "list_primitives",
        "execute_cadquery",
        "inspect_mesh",
        "render_views",
        "verify_geometry",
        "write_trace",
        "load_trace",
        "list_traces",
    }
    assert expected.issubset(exposed)


def test_trace_save_get():
    run_id = "pytest_trace"
    save_response = client.post(
        "/internal/save-trace",
        json={
            "run_id": run_id,
            "step": 1,
            "event_type": "tool_call",
            "tool_name": "echo",
            "input": {"message": "hello"},
            "output": {"ok": True},
        },
    )
    assert save_response.json()["ok"] is True

    get_response = client.post("/internal/get-trace", json={"run_id": run_id})
    payload = get_response.json()
    assert_contract(payload, "get_trace")
    assert payload["ok"] is True
    assert payload["data"]["events"][-1]["tool_name"] == "echo"


def test_validation_error_uses_common_contract():
    response = client.post(
        "/internal/save-trace",
        json={"run_id": "pytest_bad_trace", "step": "final", "event_type": "tool_call"},
    )
    payload = response.json()
    assert_contract(payload, "save_trace")
    assert payload["ok"] is False
    assert payload["error"]["code"] == "INVALID_REQUEST"
