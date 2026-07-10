"""Guard for patches/patch_fast_rlm_deadline.py — the whole-call LLM deadline.

Live failure this patch exists for: replanner turns hung 2484s/2184s/1056s
inside single chat.completions.create calls (api_timeout_ms=120000 configured
and delivered correctly) because the openai client's timeout only covers the
header phase — a response body that stalls/trickles is never aborted. The
worker heartbeats from a side thread the whole time, so Temporal (correctly)
saw a live activity and let it hang for 40+ minutes.

This test keeps two things true:
  1. The patch applies (or is already applied) to the installed fast_rlm —
     if a fast-rlm upgrade moves the anchor, this fails HERE and in the docker
     build, not silently in production as a returning 40-minute hang.
  2. The patched source has the deadline semantics we verified empirically
     (per-request AbortController signal + fresh retry loop).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

fast_rlm = pytest.importorskip("fast_rlm")

REPO = Path(__file__).resolve().parent.parent
PATCH_SCRIPT = REPO / "patches" / "patch_fast_rlm_deadline.py"
ENGINE_FILE = Path(fast_rlm.__file__).parent / "_engine" / "src" / "call_llm.ts"


def test_patch_script_applies_cleanly():
    """rc 0 covers both 'patched now' and 'already patched'; anything else
    (anchor moved, file missing) is the loud failure this guard exists for."""
    result = subprocess.run(
        [sys.executable, str(PATCH_SCRIPT)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_patched_engine_has_whole_call_deadline():
    src = ENGINE_FILE.read_text()
    assert "[GAH PATCH: whole-call deadline]" in src
    # The mechanics that actually bound the call, as verified against a
    # trickling test server: a per-request abort signal and a fresh-retry loop.
    assert "signal: ctrl.signal" in src
    assert "clearTimeout(timer)" in src
    assert "const attempts = maxRetries + 1" in src
