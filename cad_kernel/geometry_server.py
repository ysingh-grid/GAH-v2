"""
geometry_server.py — host-side MCP server for the BUILD -> VERIFY -> RENDER stage.

Runs the native stack (CadQuery/OCP + MeshLib + matplotlib) that the WASM REPL
cannot. Solids live here in a host registry; only ids + JSON reports cross back.

Tools:
  build_plan(plan)                      -> {solid_id, ok, steps, failed_step?}
  verify_solid(solid_id, ...)           -> FIXED battery report (the verdict)
  render_solid(solid_id)                -> {png_path}  (only after a build)
  build_verify_render(plan, ...)        -> one-shot convenience
  run_advisory(solid_id, fn_name, ...)  -> ADVISORY MeshLib measurement (never the verdict)
  meshlib_browse / meshlib_search / meshlib_doc  -> KB grounding for the battery/advisory

Never print to stdout (MCP channel) — use stderr.
"""
import os
import sys
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "meshlib_kb_pack" / "tools"))

import kernel
import verify as verify_mod

RENDER_DIR = Path(os.environ.get("RENDER_DIR", ROOT / "renders"))
RENDER_DIR.mkdir(exist_ok=True)

mcp = FastMCP("GeometryKernel")
_SOLIDS = {}  # solid_id -> cq solid


def _new_id():
    return "solid-" + uuid.uuid4().hex[:8]


@mcp.tool()
def build_plan(plan: dict) -> dict:
    """Execute a GeometryPlan deterministically into a solid (stored host-side).
    Returns {ok, solid_id, steps, failed_step?}. On failure, steps[].error tells
    you exactly which step broke."""
    res = kernel.build_plan(plan)
    if not res["ok"]:
        return {"ok": False, "steps": res["steps"], "failed_step": res.get("failed_step"),
                "error": res.get("error")}
    sid = _new_id()
    _SOLIDS[sid] = res["solid"]
    return {"ok": True, "solid_id": sid, "steps": res["steps"]}


@mcp.tool()
def verify_solid(solid_id: str, declared_bbox: list = None, expected_components: int = 1) -> dict:
    """Run the FIXED MeshLib battery (the VERDICT). declared_bbox = [x,y,z] from the
    plan's overall_dimensions; expected_components > 1 for intentional assemblies."""
    solid = _SOLIDS.get(solid_id)
    if solid is None:
        raise ValueError(f"unknown solid_id {solid_id!r} (build first)")
    return verify_mod.verify_solid(solid, declared_bbox=declared_bbox,
                                   expected_components=expected_components)


@mcp.tool()
def render_solid(solid_id: str) -> dict:
    """Render a built solid to a multi-view PNG (after verify). Returns {png_path}."""
    from render import render_solid as _render
    solid = _SOLIDS.get(solid_id)
    if solid is None:
        raise ValueError(f"unknown solid_id {solid_id!r} (build first)")
    out = str(RENDER_DIR / f"{solid_id}.png")
    return {"png_path": _render(solid, out)}


@mcp.tool()
def build_verify_render(plan: dict, declared_bbox: list = None,
                        expected_components: int = 1, render: bool = True) -> dict:
    """One-shot: build -> verify -> (render only if verdict passes). Mirrors the
    real flow (never render unverified geometry)."""
    b = build_plan(plan)
    if not b["ok"]:
        return {"stage": "build", **b}
    v = verify_solid(b["solid_id"], declared_bbox=declared_bbox,
                     expected_components=expected_components)
    out = {"stage": "verify", "solid_id": b["solid_id"], "verdict": v["verdict"],
           "report": v, "build_steps": b["steps"]}
    if render and v["verdict"] == "PASS":
        out["png_path"] = render_solid(b["solid_id"])["png_path"]
    return out


@mcp.tool()
def run_advisory(solid_id: str, fn_name: str, kwargs: dict = None) -> dict:
    """Run an RLM-PROPOSED MeshLib measurement as ADVISORY ONLY (never the verdict)."""
    solid = _SOLIDS.get(solid_id)
    if solid is None:
        raise ValueError(f"unknown solid_id {solid_id!r}")
    return verify_mod.run_advisory(solid, fn_name, **(kwargs or {}))


# ground the battery/advisory with the curated MeshLib KB
try:
    from meshlib_kb_tools import register as register_meshkb
    register_meshkb(mcp, kb_path=str(ROOT / "meshlib_kb_pack" / "knowledge" / "meshlib_kb.json"))
    print("[geometry_server] MeshLib KB tools registered", file=sys.stderr)
except Exception as e:
    print(f"[geometry_server] WARNING: MeshLib KB tools not registered: {e}", file=sys.stderr)


if __name__ == "__main__":
    mcp.run()
