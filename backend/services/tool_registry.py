import json
import re
from pathlib import Path

from backend.services.inspection_service import inspect_output
from backend.security.path_guard import ensure_read_allowed
from backend.utils.response import BridgeError

RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _require_string(payload: dict, key: str, tool_name: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise BridgeError("INVALID_REQUEST", f"{tool_name} requires string payload.{key}")
    return value


def _optional_dict(payload: dict, key: str) -> dict:
    value = payload.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise BridgeError("INVALID_REQUEST", f"payload.{key} must be an object")
    return value


def _validate_run_id(run_id: str, tool_name: str) -> str:
    if not RUN_ID_RE.fullmatch(run_id):
        raise BridgeError("INVALID_REQUEST", f"{tool_name} run_id may only contain letters, numbers, dot, dash, and underscore")
    return run_id


def _safe_existing_path(path: str, tool_name: str) -> str:
    resolved = ensure_read_allowed(path)
    if not resolved.exists() or not resolved.is_file():
        raise BridgeError("FILE_NOT_FOUND", f"{tool_name} file not found: {path}")
    return str(resolved)


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


def lookup_primitive(payload: dict) -> dict:
    name = payload.get("name")
    if not isinstance(name, str):
        raise BridgeError("INVALID_REQUEST", "lookup_primitive requires string payload.name")
    from tools.primitive_lookup import lookup_primitive as existing_lookup

    return existing_lookup(name)


def list_primitives(payload: dict) -> dict:
    from tools.primitive_lookup import list_primitives as existing_list

    return {"primitives": existing_list()}


def execute_cadquery(payload: dict) -> dict:
    code = _require_string(payload, "code", "execute_cadquery")
    run_id = _validate_run_id(_require_string(payload, "run_id", "execute_cadquery"), "execute_cadquery")
    from tools.execute_cadquery import execute_cadquery as existing_execute

    return existing_execute(code, run_id)


def inspect_mesh(payload: dict) -> dict:
    path = payload.get("stl_path", payload.get("path"))
    if not isinstance(path, str):
        raise BridgeError("INVALID_REQUEST", "inspect_mesh requires string payload.stl_path or payload.path")
    from tools.inspect_mesh import inspect_mesh as existing_inspect

    return existing_inspect(_safe_existing_path(path, "inspect_mesh"))


def render_views(payload: dict) -> dict:
    path = payload.get("stl_path", payload.get("path"))
    if not isinstance(path, str):
        raise BridgeError("INVALID_REQUEST", "render_views requires string payload.stl_path or payload.path")
    run_id = _validate_run_id(_require_string(payload, "run_id", "render_views"), "render_views")
    from tools.render_views import render_views as existing_render

    return existing_render(_safe_existing_path(path, "render_views"), run_id)


def verify_geometry(payload: dict) -> dict:
    prompt = _require_string(payload, "prompt", "verify_geometry")
    plan = _optional_dict(payload, "plan")
    measurements = _optional_dict(payload, "measurements")
    mesh = _optional_dict(payload, "mesh")
    renders = _optional_dict(payload, "renders")
    from tools.verify_geometry import verify_geometry as existing_verify

    return existing_verify(prompt, plan, measurements, mesh, renders)


def write_trace(payload: dict) -> dict:
    run_id = _validate_run_id(_require_string(payload, "run_id", "write_trace"), "write_trace")
    prompt = _require_string(payload, "prompt", "write_trace")
    plan = _optional_dict(payload, "plan")
    code = _require_string(payload, "code", "write_trace")
    execution_result = _optional_dict(payload, "execution_result")
    mesh_report = _optional_dict(payload, "mesh_report")
    renders = _optional_dict(payload, "renders")
    verdict = _optional_dict(payload, "verdict")
    from tools.write_trace import write_trace as existing_write

    return existing_write(run_id, prompt, plan, code, execution_result, mesh_report, renders, verdict)


def load_trace(payload: dict) -> dict:
    run_id = _validate_run_id(_require_string(payload, "run_id", "load_trace"), "load_trace")
    from tools.load_trace import load_trace as existing_load

    return existing_load(run_id)


def list_traces(payload: dict) -> dict:
    from tools.load_trace import list_traces as existing_list

    return {"traces": existing_list()}


def list_project_tools(payload: dict) -> dict:
    return {"tools": sorted(TOOLS.keys())}


TOOLS = {
    "echo": echo,
    "inspect_file_metadata": inspect_file_metadata,
    "read_json_summary": read_json_summary,
    "read_skill": read_skill,
    "list_skills": list_skills,
    "lookup_primitive": lookup_primitive,
    "list_primitives": list_primitives,
    "execute_cadquery": execute_cadquery,
    "inspect_mesh": inspect_mesh,
    "render_views": render_views,
    "verify_geometry": verify_geometry,
    "write_trace": write_trace,
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
