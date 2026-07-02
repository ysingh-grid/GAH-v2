"""
CHUNK 1 — clarify_io.py
================================================================================
The SINGLE robust implementation of asking the user a question.
Create this file at:  tools/clarify_io.py  (or wherever your tools live).

This is the ONLY place that actually asks the user. Shared by BOTH:
  (A) the pre-RLM clarifier in the orchestrator
  (B) the in-RLM MCP tool (if you also wire that)

It NEVER crashes. Fallback chain:
  1. GEOMETRY_CLARIFY_AUTO env var → returned directly (non-interactive/tests)
  2. macOS GUI dialog (osascript, frontmost app)
  3. Controlling terminal /dev/tty (works even when MCP owns stdin)
  4. Safe [UNANSWERED:...] sentinel → caller falls back to assumptions

WHAT YOU MUST ADAPT:
  - NOTHING. This file is completely self-contained. Drop it in as-is.
    If your target repo runs on Windows/Linux without a GUI, the osascript
    block silently fails and it falls through to /dev/tty, which works on
    Linux/macOS terminals. On headless Windows you'll just get the UNANSWERED
    sentinel (which is safe — the caller handles it).
================================================================================
"""

import os
import subprocess
import sys

UNANSWERED = "[UNANSWERED:NO_TERMINAL_ACCESS]"


def ask_user_impl(question: str) -> str:
    """Ask the user ONE question and return their answer (or the UNANSWERED sentinel)."""

    # -- (1) Non-interactive override (CI / tests) --
    auto = os.environ.get("GEOMETRY_CLARIFY_AUTO")
    if auto:
        return auto

    # -- (2) macOS GUI dialog (frontmost app) --
    try:
        if sys.platform == "darwin":
            safe = question.replace('"', '\\"')
            script = (
                f'tell application (path to frontmost application as text) to '
                f'display dialog "{safe}" default answer "" buttons {{"OK"}} '
                f'default button "OK" with title "Clarification"'
            )
            res = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, check=True,
            )
            out = res.stdout.strip()
            if "text returned:" in out:
                ans = out.split("text returned:", 1)[1].strip()
                if ans:
                    return ans
    except Exception as e:
        print(f"[ask_user] GUI dialog failed: {e}", file=sys.stderr)

    # -- (3) Controlling terminal (stdin is taken by MCP, but /dev/tty is free) --
    try:
        with open("/dev/tty", "r+") as tty:
            tty.write(f"\n[CLARIFY] {question}\n> ")
            tty.flush()
            ans = tty.readline().strip()
            if ans:
                return ans
    except Exception:
        pass

    # -- (4) Everyone's-out-to-lunch sentinel --
    return UNANSWERED
