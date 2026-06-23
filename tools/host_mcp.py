"""
host_mcp.py — host-side MCP server (real CPython: full OS access).

Exposes to the RLM:
  - ask_user           : clarify with the user (robust across environments)
  - read_workspace_file: read a host file
  - get_primitives_library / cadquery_browse / cadquery_search / cadquery_doc /
    cadquery_example  : the primitive library + the CadQuery knowledge base used
    for the FREEFORM planning path when no primitive fits.

Runs over stdio; never print to stdout (that is the MCP channel) — use stderr.
"""

import os
import sys
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("HostTools")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for clarify_io


@mcp.tool()
def read_workspace_file(filename: str) -> str:
    """Read a file from the host workspace filesystem.

    Args:
        filename: relative (to repo root) or absolute path.
    Returns:
        The text content of the file.
    """
    path = Path(filename)
    if not path.is_absolute():
        path = ROOT / path
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@mcp.tool()
def ask_user(question: str) -> str:
    """Ask the user ONE clarifying question and return their answer. Robust across
    environments (GUI dialog / terminal / sentinel); never crashes the run."""
    from clarify_io import ask_user_impl
    ans = ask_user_impl(question)
    # session log (so a human can audit what was asked)
    try:
        import json as _json
        log = ROOT / ".asked_clarifications.json"
        data = _json.loads(log.read_text()) if log.exists() else []
        data.append({"question": question, "answer": ans})
        log.write_text(_json.dumps(data, indent=1))
    except Exception:
        pass
    return ans



@mcp.tool()
def load_skill(topic: str) -> str:
    """Load a detailed skill on demand (keeps the base prompt small). Topics:
    'freeform' (plan a shape with the CadQuery KB when no primitive fits),
    'verify' (the build-stage verification discipline). Returns the skill text."""
    path = _SKILLS.get(topic)
    if path is None:
        return (f"[unknown skill '{topic}'] available topics: {sorted(_SKILLS)}")
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"[skill '{topic}' could not be loaded: {e}]"


@mcp.tool()
def validate_plan(plan: dict) -> dict:
    """Validate a GeometryPlan against the REAL schema (CPython Pydantic) — the
    SAME check that runs after FINAL. Call this BEFORE FINAL; you cannot validate
    in your REPL (the schema needs primitives.json, absent from the sandbox).

    Returns {valid, errors:[{location,message}], valid_primitive_types}. Every
    `primitive_type` must be one of valid_primitive_types (a library key or
    'custom') — never invent a name. Fix every error and re-validate; only FINAL
    a plan that returns valid=True.
    """
    import sys as _sys
    if str(ROOT) not in _sys.path:
        _sys.path.insert(0, str(ROOT))
    try:
        from schemas.geometry_plan import GeometryPlan, PRIMITIVES_REGISTRY
        valid_types = sorted(list(PRIMITIVES_REGISTRY.keys()) + ["custom"])
    except Exception as e:
        return {"valid": False, "errors": [{"location": "", "message": f"validator load failed: {e}"}],
                "valid_primitive_types": []}
    try:
        GeometryPlan(**plan)
        return {"valid": True, "errors": [], "valid_primitive_types": valid_types}
    except Exception as e:
        errors = []
        if hasattr(e, "errors"):
            for err in e.errors():
                loc = ".".join(str(x) for x in err.get("loc", []))
                errors.append({"location": loc, "message": err.get("msg", "")})
        else:
            errors = [{"location": "", "message": str(e)}]
        return {"valid": False, "errors": errors, "valid_primitive_types": valid_types}


# --- primitive library tool (host-side copy so the RLM can browse it via MCP) ---
@mcp.tool()
def get_primitives_library() -> dict:
    """The library of supported 3D primitives (names, parameters, defaults,
    verification). Consult this FIRST: prefer a primitive whenever one fits."""
    import json
    p = ROOT / "schemas" / "primitives.json"
    if not p.exists() and os.environ.get("PRIMITIVES_JSON"):
        p = Path(os.environ["PRIMITIVES_JSON"])
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


# --- register the CadQuery knowledge-base tools onto THIS server -------------
# (cadquery_browse / cadquery_search / cadquery_doc / cadquery_example)
try:
    sys.path.insert(0, str(ROOT / "cadquery_kb_pack" / "tools"))
    from cadquery_kb_tools import register as register_cadkb
    _kb = ROOT / "cadquery_kb_pack" / "knowledge" / "cadquery_kb.json"
    register_cadkb(mcp, kb_path=str(_kb))
    print(f"[host_mcp] CadQuery KB tools registered from {_kb}", file=sys.stderr)
except Exception as e:
    print(f"[host_mcp] WARNING: CadQuery KB tools NOT registered: {e}", file=sys.stderr)


if __name__ == "__main__":
    mcp.run()
