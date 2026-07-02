import json
import re

from backend.services.inspection_service import inspect_output
from backend.utils.response import BridgeError

RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _require_string(payload: dict, key: str, tool_name: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise BridgeError("INVALID_REQUEST", f"{tool_name} requires string payload.{key}")
    return value


def _validate_run_id(run_id: str, tool_name: str) -> str:
    if not RUN_ID_RE.fullmatch(run_id):
        raise BridgeError("INVALID_REQUEST", f"{tool_name} run_id may only contain letters, numbers, dot, dash, and underscore")
    return run_id


def echo(payload: dict) -> dict:
    return {"echo": payload}


def inspect_file_metadata(payload: dict) -> dict:
    path = payload.get("path")
    if not isinstance(path, str):
        raise BridgeError("INVALID_REQUEST", "inspect_file_metadata requires string payload.path")
    return inspect_output(path, "file_metadata")


def read_json_summary(payload: dict) -> dict:
    path = payload.get("path")
    if not isinstance(path, str):
        raise BridgeError("INVALID_REQUEST", "read_json_summary requires string payload.path")
    return inspect_output(path, "json_summary")


def read_skill(payload: dict) -> dict:
    name = _require_string(payload, "name", "read_skill")
    from tools.read_skill import read_skill as existing_read

    return {"content": existing_read(name)}


def list_skills(payload: dict) -> dict:
    from tools.read_skill import list_skills as existing_list

    return {"skills": existing_list()}


def get_primitives(payload: dict) -> dict:
    from tools.primitive_lookup import get_primitives as existing_get

    return existing_get()


def load_trace(payload: dict) -> dict:
    run_id = _validate_run_id(_require_string(payload, "run_id", "load_trace"), "load_trace")
    from tools.load_trace import load_trace as existing_load

    return existing_load(run_id)


def list_traces(payload: dict) -> dict:
    from tools.load_trace import list_traces as existing_list

    return {"traces": existing_list()}


def list_project_tools(payload: dict) -> dict:
    return {"tools": sorted(TOOLS.keys())}


# Bridge tools are intentionally limited to planning/context and inspection.
# CAD execution, mesh inspection, rendering, visual verification, and trace
# writing now run directly on the host pipeline, not through RLM HTTP tools.
TOOLS = {
    "echo": echo,
    "inspect_file_metadata": inspect_file_metadata,
    "read_json_summary": read_json_summary,
    "read_skill": read_skill,
    "list_skills": list_skills,
    "get_primitives": get_primitives,
    "load_trace": load_trace,
    "list_traces": list_traces,
    "list_project_tools": list_project_tools,
}


def execute_tool(tool_name: str, payload: dict) -> dict:
    tool = TOOLS.get(tool_name)
    if tool is None:
        raise BridgeError("UNKNOWN_TOOL", f"Unknown tool: {tool_name}")
    try:
        result = tool(payload)
    except BridgeError:
        raise
    except json.JSONDecodeError as exc:
        raise BridgeError("TOOL_FAILED", f"Tool failed to parse JSON: {exc}") from exc
    except Exception as exc:
        raise BridgeError("TOOL_FAILED", f"Tool failed: {exc}") from exc
    return {"tool_name": tool_name, "result": result}
