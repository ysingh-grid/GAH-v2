"""
clarify_io.py — the single, robust implementation of asking the user a question.

Shared by host_mcp.ask_user (the MCP tool) and by the orchestrator's dedicated
clarifier step. Never crashes the run:
  1. GEOMETRY_CLARIFY_AUTO env var -> returned directly (non-interactive / tests)
  2. macOS GUI dialog (osascript, frontmost app)
  3. controlling terminal /dev/tty (works though MCP owns stdin)
  4. a safe [UNANSWERED:...] sentinel so the caller can fall back to assumptions
"""

import os
import subprocess
import sys

UNANSWERED = "[UNANSWERED:NO_TERMINAL_ACCESS]"


def ask_user_impl(question: str) -> str:
    """Ask the user ONE question and return their answer (or the UNANSWERED sentinel)."""
    auto = os.environ.get("GEOMETRY_CLARIFY_AUTO")
    if auto:
        return auto

    # macOS GUI dialog
    try:
        if sys.platform == "darwin":
            safe = question.replace('"', '\\"')
            script = (f'tell application (path to frontmost application as text) to '
                      f'display dialog "{safe}" default answer "" buttons {{"OK"}} '
                      f'default button "OK" with title "Geometry Agent Harness: Clarification"')
            res = subprocess.run(["osascript", "-e", script],
                                 capture_output=True, text=True, check=True)
            out = res.stdout.strip()
            if "text returned:" in out:
                ans = out.split("text returned:", 1)[1].strip()
                if ans:
                    return ans
    except Exception as e:
        print(f"[ask_user] GUI dialog failed: {e}", file=sys.stderr)

    # controlling terminal (stdin is taken by MCP, but /dev/tty is free)
    try:
        with open("/dev/tty", "r+") as tty:
            tty.write(f"\n[CLARIFY] {question}\n> ")
            tty.flush()
            ans = tty.readline().strip()
            if ans:
                return ans
    except Exception:
        pass

    return UNANSWERED
