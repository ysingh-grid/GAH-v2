"""Unit tests for tools/execute_cadquery.py — the sole deterministic driver
that turns compiled CadQuery source into a solid + metrics (or a diagnosable
failure). Covers the timeout/diagnostics hardening: a live "table_spoon" run
crashed filleting a smooth loft's spline rim, then TIMED OUT on the replanner's
retry with a smaller radius — the bare "timed out after 30 seconds" gave the
replanner zero signal about which step never returned.
"""

from __future__ import annotations

import shutil
import sys

import pytest

from runtime.compile_cadquery import compile_plan_to_cadquery
from runtime.schema import plan_from_dict, load_library
from tools.artifacts import new_run_id, run_dir

# tools/__init__.py does `from .execute_cadquery import execute_cadquery`, which
# rebinds the `execute_cadquery` ATTRIBUTE on the `tools` package to the
# function, shadowing the submodule — `from tools import execute_cadquery`
# therefore gets the function, not the module, and monkeypatch.setattr on a
# function object silently does nothing useful. Import the real submodule
# object out of sys.modules (importing `tools` above already imported it as a
# side effect of that same __init__.py line).
ec = sys.modules["tools.execute_cadquery"]

LIBRARY = load_library()


def _run(run_id, fn):
    try:
        return fn()
    finally:
        shutil.rmtree(run_dir(run_id), ignore_errors=True)


def test_stage_markers_do_not_break_success_json_parsing():
    """Progress-marker print() lines precede the final JSON line; parsing must
    take the LAST non-empty line, not treat all of stdout as one JSON blob."""
    pytest.importorskip("cadquery")
    plan = plan_from_dict(
        {
            "part_name": "cube",
            "steps": [
                {
                    "id": "b", "primitive": "box", "operation": "base",
                    "parameters": {"length": 10.0, "width": 10.0, "height": 10.0},
                }
            ],
        }
    )
    code = compile_plan_to_cadquery(plan, LIBRARY)
    assert "[STAGE 1/1]" in code  # the marker really is in the compiled script
    run_id = new_run_id("test_exec")
    result = _run(run_id, lambda: ec.execute_cadquery(code, run_id))
    assert result["success"], result.get("error")
    assert abs(result["volume"] - 1000.0) < 1.0


def test_crash_error_is_prefixed_with_the_failing_stage(monkeypatch):
    """A raw exception traceback names a codegen LINE NUMBER, useless to the
    replanner. The error must instead be prefixed with the [STAGE n/m] marker
    naming the actual step id + op that was running when it crashed."""
    user_code = (
        "print('[STAGE 1/2] harmless (primitive:box)', flush=True)\n"
        "print('[STAGE 2/2] boom (finish:fillet)', flush=True)\n"
        "raise ValueError('simulated OCCT failure')\n"
    )
    run_id = new_run_id("test_exec_crash")
    result = _run(run_id, lambda: ec.execute_cadquery(user_code, run_id))
    assert result["success"] is False
    assert result["error"].startswith("[STAGE 2/2] boom (finish:fillet):")
    assert "simulated OCCT failure" in result["error"]


def test_timeout_reports_last_stage_reached(monkeypatch):
    """The must-fix gap: a genuinely slow/hung OCCT op used to come back as a
    bare 'timed out after 30 seconds' with NO signal about where. Verify the
    subprocess.TimeoutExpired path surfaces the last [STAGE] marker that
    printed before the kill (proven live: TimeoutExpired.stdout IS populated
    with pre-kill output) and does not silently hang the test suite itself —
    bounded to ~1s via a monkeypatched timeout, not the real 300s ceiling."""
    monkeypatch.setattr(ec, "_SUBPROCESS_TIMEOUT_S", 1)
    user_code = (
        "import time\n"
        "print('[STAGE 1/3] outer_bowl (primitive:loft_between)', flush=True)\n"
        "print('[STAGE 2/3] handle (primitive:sweep)', flush=True)\n"
        "print('[STAGE 3/3] fillet_rim (finish:fillet)', flush=True)\n"
        "time.sleep(30)\n"  # never reached within the 1s monkeypatched ceiling
    )
    run_id = new_run_id("test_exec_timeout")
    result = _run(run_id, lambda: ec.execute_cadquery(user_code, run_id))
    assert result["success"] is False
    assert "did not finish within 1s" in result["error"]
    assert "[STAGE 3/3] fillet_rim (finish:fillet)" in result["error"]
    assert "simplifying" in result["error"]  # actionable hint, not just "it failed"


def test_timeout_with_no_stage_reached_gives_a_clear_hint(monkeypatch):
    """If the process hangs before its first print (e.g. interpreter startup),
    say so explicitly rather than silently omitting the stage hint."""
    monkeypatch.setattr(ec, "_SUBPROCESS_TIMEOUT_S", 1)
    user_code = "import time\ntime.sleep(30)\n"  # no [STAGE] print at all
    run_id = new_run_id("test_exec_timeout_nostage")
    result = _run(run_id, lambda: ec.execute_cadquery(user_code, run_id))
    assert result["success"] is False
    assert "hang was in import/setup" in result["error"]


def test_default_timeout_is_generous_not_the_old_30s():
    """Regression guard: the old 30s ceiling produced false failures on valid
    but slow geometry (measured live). Must stay well above 30s."""
    assert ec._SUBPROCESS_TIMEOUT_S >= 120
