"""
CHUNK 6 (OPTIONAL) — host_mcp.py ask_user MCP TOOL
================================================================================
Only needed if you want the RLM agent ITSELF to call ask_user during its
build/verify loop (in addition to the orchestrator's pre-RLM clarifier).

This wires the SAME ask_user_impl (Chunk 1) into your MCP server so the
agent can call:  await mcp_call('your_server','ask_user', question="...")

Create at: tools/host_mcp.py  (or wherever your MCP server lives)

WHAT YOU MUST ADAPT:
  - `from clarify_io import ask_user_impl` — adjust the import path to
    wherever you placed Chunk 1.
  - `ROOT = Path(__file__).resolve().parent.parent` — adjust if your
    project layout is different.
  - The audit-log path (`.asked_clarifications.json`) — change or remove.
  - If you use a different MCP framework (not FastMCP), adapt the decorator.
  - If your repo doesn't use MCP at all, you can skip this entire chunk.
    The pre-RLM clarifier (Chunks 1-5) is sufficient by itself.
================================================================================
"""

import sys
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("HostTools")

# Ensure clarify_io is importable (adjust path to your layout)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for clarify_io


@mcp.tool()
def ask_user(question: str) -> str:
    """
    Ask the user ONE clarifying question and return their answer.
    Robust across environments (GUI dialog / terminal / sentinel);
    never crashes the run.
    """
    from clarify_io import ask_user_impl
    ans = ask_user_impl(question)

    # Optional: session audit log (so a human can audit what was asked)
    try:
        import json as _json
        log = ROOT / ".asked_clarifications.json"
        data = _json.loads(log.read_text()) if log.exists() else []
        data.append({"question": question, "answer": ans})
        log.write_text(_json.dumps(data, indent=1))
    except Exception:
        pass

    return ans


if __name__ == "__main__":
    mcp.run()
