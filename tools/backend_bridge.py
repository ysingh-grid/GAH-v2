"""
Backend bridge tools for fast_rlm.

fast_rlm serializes each tool function independently into a Pyodide sandbox.
For that reason every function below is self-contained: no shared helpers,
no project imports, and no advanced type annotations.
"""


def backend_list_skills():
    """List skill markdown files through the backend bridge."""
    import json
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    response = requests.post(f"{url}/internal/list-skills", headers={"Content-Type": "application/json"}, data=json.dumps({}), timeout=30)
    return response.json()


def backend_read_skill(skill_name):
    """Read one skill markdown file through the backend bridge."""
    import json
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {"skill_name": skill_name}
    response = requests.post(f"{url}/internal/read-skill", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
    return response.json()


def backend_load_skill_pack(skill_names_json):
    """Load multiple skills as one usable markdown pack. skill_names_json must be a JSON list of skill names."""
    import json
    import os
    import requests

    try:
        skill_names = json.loads(skill_names_json or "[]")
    except Exception:
        skill_names = []
    if not isinstance(skill_names, list):
        skill_names = []

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    loaded = []
    missing = []
    sections = []
    for name in skill_names:
        payload = {"skill_name": str(name)}
        response = requests.post(f"{url}/internal/read-skill", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
        result = response.json()
        if result.get("ok") and isinstance(result.get("data"), dict):
            skill_name = result["data"].get("skill_name", str(name))
            content = result["data"].get("content", "")
            loaded.append(skill_name)
            sections.append(f"## {skill_name}\n\n{content}")
        else:
            missing.append(str(name))
    return {
        "ok": True,
        "tool": "load_skill_pack",
        "data": {
            "loaded": loaded,
            "missing": missing,
            "skill_pack": "\n\n---\n\n".join(sections),
        },
        "error": None,
        "run_id": None,
        "trace_id": None,
    }


def backend_scan_repo(path=".", max_depth=3):
    """Scan safe repository files through the backend bridge."""
    import json
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {"path": path, "max_depth": max_depth}
    response = requests.post(f"{url}/internal/scan-repo", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
    return response.json()


def backend_read_file(path):
    """Read a safe text file through the backend bridge."""
    import json
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {"path": path}
    response = requests.post(f"{url}/internal/read-file", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
    return response.json()


def backend_write_file(path, content, overwrite=True):
    """Write a safe generated/output file through the backend bridge."""
    import json
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {"path": path, "content": content, "overwrite": overwrite}
    response = requests.post(f"{url}/internal/write-file", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
    return response.json()


def backend_list_dir(path="."):
    """List one safe directory through the backend bridge."""
    import json
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {"path": path}
    response = requests.post(f"{url}/internal/list-dir", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
    return response.json()


def backend_run_pipeline(pipeline_name, args_json="{}", run_id="rlm_full_demo"):
    """Run an allowlisted backend pipeline. args_json must be a JSON object string."""
    import json
    import os
    import requests

    try:
        args = json.loads(args_json or "{}")
    except Exception:
        args = {}
    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {"pipeline_name": pipeline_name, "args": args, "run_id": run_id}
    response = requests.post(f"{url}/internal/run-pipeline", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
    return response.json()


def backend_execute_tool(tool_name, payload_json="{}", run_id="rlm_full_demo"):
    """Execute an allowlisted backend tool. payload_json must be a JSON object string."""
    import json
    import os
    import requests

    try:
        payload_data = json.loads(payload_json or "{}")
    except Exception:
        payload_data = {}
    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {"tool_name": tool_name, "payload": payload_data, "run_id": run_id}
    response = requests.post(f"{url}/internal/execute-tool", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
    return response.json()


def backend_list_primitives(run_id="rlm_full_demo"):
    """List available primitive names through the backend allowlisted tool registry."""
    import json
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {"tool_name": "list_primitives", "payload": {}, "run_id": run_id}
    response = requests.post(f"{url}/internal/execute-tool", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
    return response.json()


def backend_lookup_primitive(name, run_id="rlm_full_demo"):
    """Look up one primitive schema through the backend allowlisted tool registry."""
    import json
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {"tool_name": "lookup_primitive", "payload": {"name": name}, "run_id": run_id}
    response = requests.post(f"{url}/internal/execute-tool", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
    return response.json()


def backend_list_project_tools(run_id="rlm_full_demo"):
    """List every backend allowlisted project tool available to RLM."""
    import json
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {"tool_name": "list_project_tools", "payload": {}, "run_id": run_id}
    response = requests.post(f"{url}/internal/execute-tool", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
    return response.json()


def backend_execute_cadquery(code, run_id="rlm_cad_run"):
    """Execute CadQuery code through the backend allowlisted project tool."""
    import json
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {"tool_name": "execute_cadquery", "payload": {"code": code, "run_id": run_id}, "run_id": run_id}
    response = requests.post(f"{url}/internal/execute-tool", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=60)
    return response.json()


def backend_inspect_mesh(stl_path, run_id="rlm_cad_run"):
    """Inspect an STL mesh through the backend allowlisted project tool."""
    import json
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {"tool_name": "inspect_mesh", "payload": {"stl_path": stl_path}, "run_id": run_id}
    response = requests.post(f"{url}/internal/execute-tool", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=60)
    return response.json()


def backend_render_views(stl_path, run_id="rlm_cad_run"):
    """Render STL front/top/isometric views through the backend allowlisted project tool."""
    import json
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {"tool_name": "render_views", "payload": {"stl_path": stl_path, "run_id": run_id}, "run_id": run_id}
    response = requests.post(f"{url}/internal/execute-tool", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=60)
    return response.json()


def backend_verify_geometry(prompt, plan_json="{}", measurements_json="{}", mesh_json="{}", renders_json="{}", run_id="rlm_cad_run"):
    """Verify geometry using the project verifier through the backend allowlisted tool."""
    import json
    import os
    import requests

    def parse_object(value):
        try:
            parsed = json.loads(value or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {
        "tool_name": "verify_geometry",
        "payload": {
            "prompt": prompt,
            "plan": parse_object(plan_json),
            "measurements": parse_object(measurements_json),
            "mesh": parse_object(mesh_json),
            "renders": parse_object(renders_json),
        },
        "run_id": run_id,
    }
    response = requests.post(f"{url}/internal/execute-tool", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=90)
    return response.json()


def backend_write_trace(run_id, prompt, plan_json="{}", code="", execution_result_json="{}", mesh_report_json="{}", renders_json="{}", verdict_json="{}"):
    """Write a complete project trace through the backend allowlisted project tool."""
    import json
    import os
    import requests

    def parse_object(value):
        try:
            parsed = json.loads(value or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {
        "tool_name": "write_trace",
        "payload": {
            "run_id": run_id,
            "prompt": prompt,
            "plan": parse_object(plan_json),
            "code": code,
            "execution_result": parse_object(execution_result_json),
            "mesh_report": parse_object(mesh_report_json),
            "renders": parse_object(renders_json),
            "verdict": parse_object(verdict_json),
        },
        "run_id": run_id,
    }
    response = requests.post(f"{url}/internal/execute-tool", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=60)
    return response.json()


def backend_load_trace(run_id):
    """Load a complete project trace through the backend allowlisted project tool."""
    import json
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {"tool_name": "load_trace", "payload": {"run_id": run_id}, "run_id": run_id}
    response = requests.post(f"{url}/internal/execute-tool", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
    return response.json()


def backend_list_traces(run_id="rlm_full_demo"):
    """List complete project traces through the backend allowlisted project tool."""
    import json
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {"tool_name": "list_traces", "payload": {}, "run_id": run_id}
    response = requests.post(f"{url}/internal/execute-tool", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
    return response.json()


def backend_build_skill_tool_report(run_id="rlm_full_demo"):
    """Build the canonical skill/tool demo report through backend APIs and return clean summary data."""
    import json
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    headers = {"Content-Type": "application/json"}
    state_trace = []
    def summarize_response(response):
        if not isinstance(response, dict):
            return {"type": type(response).__name__}
        data = response.get("data")
        summary = {
            "ok": response.get("ok"),
            "tool": response.get("tool"),
            "error": response.get("error"),
        }
        if isinstance(data, dict):
            summary["data_keys"] = sorted(data.keys())
        elif isinstance(data, list):
            summary["data_type"] = "list"
            summary["data_len"] = len(data)
        else:
            summary["data_type"] = type(data).__name__
        return summary

    def record_state(step, rlm_tool, backend_endpoint, request_payload, response, parsed):
        state_trace.append(
            {
                "step": step,
                "rlm_tool": rlm_tool,
                "backend_endpoint": backend_endpoint,
                "request": request_payload,
                "response_contract": summarize_response(response),
                "parsed_by_rlm_tool": parsed,
            }
        )

    health = requests.get(f"{url}/internal/health", timeout=30).json()
    if isinstance(health, dict) and health.get("ok") and isinstance(health.get("data"), dict):
        health["data"]["backend_url"] = url
    record_state(
        1,
        "backend_build_skill_tool_report",
        "GET /internal/health",
        {},
        health,
        {"backend_url": health.get("data", {}).get("backend_url"), "status": health.get("data", {}).get("status")},
    )

    skills_response = requests.post(f"{url}/internal/list-skills", headers=headers, data=json.dumps({}), timeout=30).json()
    listed_skills = skills_response.get("data", {}).get("skills", [])
    listed_skill_names = [item.get("name", "") for item in listed_skills if isinstance(item, dict)]
    skill_names_to_load = listed_skill_names
    record_state(
        2,
        "backend_build_skill_tool_report",
        "POST /internal/list-skills",
        {},
        skills_response,
        {"skill_count": len(listed_skill_names), "skill_names": listed_skill_names},
    )

    project_tools_response = requests.post(
        f"{url}/internal/execute-tool",
        headers=headers,
        data=json.dumps({"tool_name": "list_project_tools", "payload": {}, "run_id": run_id}),
        timeout=30,
    ).json()
    exposed_project_tools = project_tools_response.get("data", {}).get("result", {}).get("tools", [])
    record_state(
        3,
        "backend_build_skill_tool_report",
        "POST /internal/execute-tool",
        {"tool_name": "list_project_tools", "payload": {}, "run_id": run_id},
        project_tools_response,
        {"exposed_tool_count": len(exposed_project_tools), "exposed_project_tools": exposed_project_tools},
    )

    loaded_skills = []
    skill_pack_sections = []
    for index, name in enumerate(skill_names_to_load, start=4):
        skill_response = requests.post(
            f"{url}/internal/read-skill",
            headers=headers,
            data=json.dumps({"skill_name": name}),
            timeout=30,
        ).json()
        if skill_response.get("ok") and isinstance(skill_response.get("data"), dict):
            loaded_skills.append(name)
            content = skill_response["data"].get("content", "")
            skill_pack_sections.append({"name": name, "chars": len(content)})
            parsed = {"loaded": name, "content_chars": len(content)}
        else:
            parsed = {"loaded": None, "requested": name}
        record_state(
            index,
            "backend_build_skill_tool_report",
            "POST /internal/read-skill",
            {"skill_name": name},
            skill_response,
            parsed,
        )

    primitives_response = requests.post(
        f"{url}/internal/execute-tool",
        headers=headers,
        data=json.dumps({"tool_name": "list_primitives", "payload": {}, "run_id": run_id}),
        timeout=30,
    ).json()
    primitive_names = primitives_response.get("data", {}).get("result", {}).get("primitives", [])
    record_state(
        10,
        "backend_build_skill_tool_report",
        "POST /internal/execute-tool",
        {"tool_name": "list_primitives", "payload": {}, "run_id": run_id},
        primitives_response,
        {"primitive_count": len(primitive_names), "primitive_names": primitive_names},
    )

    selected_primitives = {}
    for index, primitive_name in enumerate(["box", "cylinder"], start=11):
        primitive_response = requests.post(
            f"{url}/internal/execute-tool",
            headers=headers,
            data=json.dumps({"tool_name": "lookup_primitive", "payload": {"name": primitive_name}, "run_id": run_id}),
            timeout=30,
        ).json()
        selected_primitives[primitive_name] = primitive_response.get("data", {}).get("result", {})
        record_state(
            index,
            "backend_build_skill_tool_report",
            "POST /internal/execute-tool",
            {"tool_name": "lookup_primitive", "payload": {"name": primitive_name}, "run_id": run_id},
            primitive_response,
            {
                "selected_primitive": primitive_name,
                "schema_keys": sorted(selected_primitives[primitive_name].keys()) if isinstance(selected_primitives[primitive_name], dict) else [],
            },
        )

    repo_response = requests.post(
        f"{url}/internal/scan-repo",
        headers=headers,
        data=json.dumps({"path": ".", "max_depth": 2}),
        timeout=30,
    ).json()
    repo_file_count = len(repo_response.get("data", {}).get("files", []))
    record_state(
        13,
        "backend_build_skill_tool_report",
        "POST /internal/scan-repo",
        {"path": ".", "max_depth": 2},
        repo_response,
        {"repo_file_count": repo_file_count},
    )

    tools_dir_response = requests.post(
        f"{url}/internal/list-dir",
        headers=headers,
        data=json.dumps({"path": "tools"}),
        timeout=30,
    ).json()
    tools_dir_count = len(tools_dir_response.get("data", {}).get("items", []))
    record_state(
        14,
        "backend_build_skill_tool_report",
        "POST /internal/list-dir",
        {"path": "tools"},
        tools_dir_response,
        {"tools_dir_count": tools_dir_count},
    )

    pipeline_response = requests.post(
        f"{url}/internal/run-pipeline",
        headers=headers,
        data=json.dumps({"pipeline_name": "repo_check", "args": {}, "run_id": run_id}),
        timeout=30,
    ).json()
    pipeline_status = pipeline_response.get("data", {}).get("status", "unknown")
    record_state(
        15,
        "backend_build_skill_tool_report",
        "POST /internal/run-pipeline",
        {"pipeline_name": "repo_check", "args": {}, "run_id": run_id},
        pipeline_response,
        {"pipeline_status": pipeline_status},
    )

    echo_response = requests.post(
        f"{url}/internal/execute-tool",
        headers=headers,
        data=json.dumps({"tool_name": "echo", "payload": {"message": "fast_rlm reached backend tools"}, "run_id": run_id}),
        timeout=30,
    ).json()
    echo_message = echo_response.get("data", {}).get("result", {}).get("echo", {}).get("message", "")
    record_state(
        16,
        "backend_build_skill_tool_report",
        "POST /internal/execute-tool",
        {"tool_name": "echo", "payload": {"message": "fast_rlm reached backend tools"}, "run_id": run_id},
        echo_response,
        {"echo_message": echo_message},
    )

    cad_plan = [
        "Use SKILLS/overview to understand the RLM bridge workflow.",
        "Use intent_extraction to identify a 20 x 10 x 5 mm rectangular box with a top cylinder.",
        "Use part_decomposition to split the design into base box and top cylinder.",
        "Use primitive_planning to select box and cylinder primitives.",
        "Use dimension_reasoning to set box length=20, width=10, height=5 and cylinder radius=2.",
        "Use cadquery_cookbook to union the cylinder onto the +Z face of the box.",
        "Use verification_planning to check dimensions, cylinder radius, and merged solid integrity.",
        "Use repair_guidance, refinement_guidance, debugging, and repo_migration if execution or migration issues appear.",
    ]

    report = {
        "backend_url": url,
        "skill_names": listed_skill_names,
        "loaded_skills": loaded_skills,
        "used_skill_sections": loaded_skills,
        "skill_pack_sections": skill_pack_sections,
        "exposed_project_tools": exposed_project_tools,
        "primitive_names": primitive_names,
        "selected_primitives": list(selected_primitives.keys()),
        "selected_primitive_schemas": selected_primitives,
        "cad_plan": cad_plan,
        "repo_file_count": repo_file_count,
        "tools_dir_count": tools_dir_count,
        "pipeline_status": pipeline_status,
        "echo_message": echo_message,
        "generated_report_path": "generated/rlm_full_demo_report.json",
        "state_trace": state_trace,
    }

    write_response = requests.post(
        f"{url}/internal/write-file",
        headers=headers,
        data=json.dumps({"path": "generated/rlm_full_demo_report.json", "content": json.dumps(report, indent=2), "overwrite": True}),
        timeout=30,
    ).json()
    record_state(
        17,
        "backend_build_skill_tool_report",
        "POST /internal/write-file",
        {"path": "generated/rlm_full_demo_report.json", "overwrite": True},
        write_response,
        {"generated_report_path": "generated/rlm_full_demo_report.json"},
    )
    report["state_trace"] = state_trace
    requests.post(
        f"{url}/internal/write-file",
        headers=headers,
        data=json.dumps({"path": "generated/rlm_full_demo_report.json", "content": json.dumps(report, indent=2), "overwrite": True}),
        timeout=30,
    )
    trace_response = requests.post(
        f"{url}/internal/save-trace",
        headers=headers,
        data=json.dumps(
            {
                "run_id": run_id,
                "step": 18,
                "event_type": "full_rlm_skill_tool_demo",
                "tool_name": "fast_rlm",
                "input": {"loaded_skills": loaded_skills, "selected_primitives": list(selected_primitives.keys())},
                "output": {"report_path": "generated/rlm_full_demo_report.json", "repo_file_count": repo_file_count},
            }
        ),
        timeout=30,
    ).json()
    record_state(
        18,
        "backend_build_skill_tool_report",
        "POST /internal/save-trace",
        {"run_id": run_id, "step": 18, "event_type": "full_rlm_skill_tool_demo"},
        trace_response,
        {"trace_path": trace_response.get("data", {}).get("trace_path")},
    )
    report["state_trace"] = state_trace
    requests.post(
        f"{url}/internal/write-file",
        headers=headers,
        data=json.dumps({"path": "generated/rlm_full_demo_report.json", "content": json.dumps(report, indent=2), "overwrite": True}),
        timeout=30,
    )
    return {
        "ok": True,
        "tool": "build_skill_tool_report",
        "data": report,
        "error": None,
        "run_id": run_id,
        "trace_id": None,
    }


def backend_inspect_output(path, inspection_type="file_metadata"):
    """Inspect a backend output artifact."""
    import json
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {"path": path, "inspection_type": inspection_type}
    response = requests.post(f"{url}/internal/inspect-output", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
    return response.json()


def backend_save_trace(run_id, step, event_type, tool_name="fast_rlm", input_json="{}", output_json="{}"):
    """Save an explicit trace event through the backend bridge."""
    import json
    import os
    import requests

    try:
        step_value = int(step)
    except Exception:
        step_value = 0
    try:
        input_payload = json.loads(input_json or "{}")
    except Exception:
        input_payload = {"raw": input_json}
    try:
        output_payload = json.loads(output_json or "{}")
    except Exception:
        output_payload = {"raw": output_json}
    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {
        "run_id": run_id,
        "step": step_value,
        "event_type": event_type,
        "tool_name": tool_name,
        "input": input_payload,
        "output": output_payload,
    }
    response = requests.post(f"{url}/internal/save-trace", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
    return response.json()


def backend_health():
    """Check backend health and return the backend project root/status."""
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    response = requests.get(f"{url}/internal/health", timeout=30)
    data = response.json()
    if isinstance(data, dict) and data.get("ok") and isinstance(data.get("data"), dict):
        data["data"]["backend_url"] = url
    return data


def backend_get_trace(run_id):
    """Fetch a saved trace through the backend bridge."""
    import json
    import os
    import requests

    url = os.getenv("DTCM_BACKEND_URL", "http://localhost:8001").rstrip("/")
    payload = {"run_id": run_id}
    response = requests.post(f"{url}/internal/get-trace", headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
    return response.json()


BACKEND_BRIDGE_TOOLS = [
    backend_list_skills,
    backend_read_skill,
    backend_load_skill_pack,
    backend_scan_repo,
    backend_read_file,
    backend_write_file,
    backend_list_dir,
    backend_run_pipeline,
    backend_execute_tool,
    backend_list_primitives,
    backend_lookup_primitive,
    backend_list_project_tools,
    backend_execute_cadquery,
    backend_inspect_mesh,
    backend_render_views,
    backend_verify_geometry,
    backend_write_trace,
    backend_load_trace,
    backend_list_traces,
    backend_build_skill_tool_report,
    backend_inspect_output,
    backend_save_trace,
    backend_get_trace,
    backend_health,
]
