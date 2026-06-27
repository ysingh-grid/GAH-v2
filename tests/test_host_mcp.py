"""
test_host_mcp.py — spawn the real host MCP server over stdio (exactly how
fast-rlm launches it) and confirm every planning tool responds: ask_user,
get_primitives_library, and the CadQuery KB tools. No LLM involved.

Run:  GEOMETRY_CLARIFY_AUTO="M4, 80x60" python tests/test_host_mcp.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent


def pay(r):
    sc = getattr(r, "structuredContent", None)
    if sc:
        return sc
    t = "\n".join(getattr(c, "text", "") for c in r.content)
    try:
        return json.loads(t)
    except Exception:
        return t


async def main():
    os.environ.setdefault("GEOMETRY_CLARIFY_AUTO", "Use M4 bolts, 80x60mm footprint")
    params = StdioServerParameters(command=sys.executable,
                                   args=[str(ROOT / "tools" / "host_mcp.py")],
                                   env=dict(os.environ))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            print("host tools:", tools)
            assert {"ask_user", "validate_plan", "load_skill", "get_primitives_library",
                    "cadquery_search", "cadquery_doc", "cadquery_browse", "cadquery_example"} <= set(tools)
            assert "declare_gap_ledger" not in tools  # removed: enforcement moved to a clean clarifier
            assert pay(await s.call_tool("ask_user", {"question": "?"}))["result"]
            # validate_plan: a valid plan passes; an invented primitive_type is rejected with the valid list
            good = {"title": "t", "overall_dimensions": {"width": 40, "length": 20, "height": 10},
                    "engineering_requirements": {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []},
                    "assumptions": ["x"], "clarifications": [],
                    "primitives_sequence": [{"sequence_id": 1, "name": "b", "primitive_type": "box", "parameters": {"length": 40, "width": 20, "height": 10}, "operation": "new", "rationale": "the base plate body of the part"}]}
            vr = pay(await s.call_tool("validate_plan", {"plan": good}))
            vr = vr.get("result", vr) if isinstance(vr, dict) and "result" in vr else vr
            assert vr["valid"] is True, vr
            bad = {**good, "primitives_sequence": [{**good["primitives_sequence"][0], "primitive_type": "rounded_box"}]}
            vr2 = pay(await s.call_tool("validate_plan", {"plan": bad}))
            vr2 = vr2.get("result", vr2) if isinstance(vr2, dict) and "result" in vr2 else vr2
            assert vr2["valid"] is False and "filleted_box" in vr2["valid_primitive_types"], vr2
            assert len(pay(await s.call_tool("get_primitives_library", {}))) >= 30  # rich vocabulary
            assert pay(await s.call_tool("cadquery_search", {"query": "revolve a profile"}))["api"]
            assert pay(await s.call_tool("cadquery_doc", {"id_or_name": "Workplane.revolve"}))["signature"]
    print("HOST MCP SERVER: all planning tools respond \u2713")


if __name__ == "__main__":
    asyncio.run(main())
