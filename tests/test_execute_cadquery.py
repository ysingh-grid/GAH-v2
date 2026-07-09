"""Unit tests for the pure failure-attribution helpers in execute_cadquery.

These need no CadQuery / subprocess — they only exercise reading the progress
sidecar and prepending an attribution to an error string, so a segfault (-11)
or a caught StdFail can name the exact failing step. Topology failure messages
are pure strings so the replanner gets a truthful severing-cut diagnosis.
"""

from __future__ import annotations

from tools.execute_cadquery import (
    _attribute_failure,
    _read_progress_marker,
    multi_shell_failure_detail,
    multi_solid_failure_detail,
)


def test_read_progress_marker_parses_step_and_label(tmp_path):
    p = tmp_path / "_progress.txt"
    p.write_text("hollow_out_bottle :: finish shell", encoding="utf-8")
    assert _read_progress_marker(str(p)) == "step 'hollow_out_bottle' (op: finish shell)"


def test_read_progress_marker_missing_file_returns_none(tmp_path):
    assert _read_progress_marker(str(tmp_path / "nope.txt")) is None


def test_attribute_failure_prepends_step_when_marker_present(tmp_path):
    p = tmp_path / "_progress.txt"
    p.write_text("cup_body :: base cylinder", encoding="utf-8")
    out = _attribute_failure("BRep_API: command not done", str(p))
    assert out.startswith("failed at step 'cup_body' (op: base cylinder): ")
    assert "BRep_API: command not done" in out


def test_attribute_failure_is_passthrough_when_no_marker(tmp_path):
    err = "Python interpreter crashed with return code -11. Stderr: "
    assert _attribute_failure(err, str(tmp_path / "nope.txt")) == err


def test_multi_solid_failure_detail_names_count_and_geometric_cause():
    """Multi-solid messages are geometric (cut_sever/union_gap), not product recipes."""
    msg = multi_solid_failure_detail(2, op_hint="cut cylinder")
    assert "2 solids" in msg
    assert "exactly 1" in msg
    assert "cut_sever" in msg.lower() or "cut" in msg.lower()
    assert "hollow_cylinder" not in msg  # no vessel special-case
    msg_u = multi_solid_failure_detail(2, op_hint="union box")
    assert "union" in msg_u.lower()


def test_multi_solid_failure_detail_zero_solids_is_still_actionable():
    msg = multi_solid_failure_detail(0)
    assert "0 solids" in msg
    assert "exactly 1" in msg


def test_multi_shell_failure_detail_names_enclosed_void():
    msg = multi_shell_failure_detail(2)
    assert "2 shells" in msg
    assert "1 solid" in msg
    assert "enclosed" in msg.lower() or "void" in msg.lower() or "cavity" in msg.lower()
    assert "TOUCH" not in msg


# ── Integration (needs CadQuery in the subprocess interpreter) ──────────────

import pytest

from tools.execute_cadquery import execute_cadquery


def _cadquery_available() -> bool:
    try:
        import cadquery  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _cadquery_available(), reason="cadquery not installed")
def test_execute_cadquery_reports_topology_on_single_solid(tmp_path, monkeypatch):
    """Open box → exactly 1 solid; metrics include num_solids/num_shells."""
    from tools import artifacts

    monkeypatch.setattr(artifacts, "run_dir", lambda run_id: tmp_path / run_id)
    code = (
        "import cadquery as cq\n"
        "result = cq.Workplane('XY').box(20, 20, 20)\n"
    )
    out = execute_cadquery(code, "topo_single")
    assert out.get("success") is True, out
    assert out.get("num_solids") == 1
    assert out.get("num_shells") == 1
    assert out.get("stl_path")


@pytest.mark.skipif(not _cadquery_available(), reason="cadquery not installed")
def test_execute_cadquery_fails_on_multi_solid_with_severing_diagnosis(
    tmp_path, monkeypatch
):
    """Two disjoint boxes → num_solids=2, success=False, severing-cut CAUSE."""
    from tools import artifacts

    monkeypatch.setattr(artifacts, "run_dir", lambda run_id: tmp_path / run_id)
    # Two non-overlapping boxes unioned → multi-solid compound (or 2 solids).
    code = (
        "import cadquery as cq\n"
        "a = cq.Workplane('XY').box(10, 10, 10)\n"
        "b = cq.Workplane('XY').box(10, 10, 10).translate((50, 0, 0)\n"
        ")\n"
        "result = a.union(b)\n"
    )
    out = execute_cadquery(code, "topo_multi")
    assert out.get("success") is False, out
    assert out.get("num_solids", 0) >= 2
    err = str(out.get("error", ""))
    assert "solids" in err
    assert "CAUSE" in err
    assert "TOUCH" not in err


@pytest.mark.skipif(not _cadquery_available(), reason="cadquery not installed")
def test_execute_cadquery_fails_on_enclosed_void_multi_shell(tmp_path, monkeypatch):
    """Fully internal cavity → 1 solid, 2 shells → fail with multi-shell CAUSE."""
    from tools import artifacts

    monkeypatch.setattr(artifacts, "run_dir", lambda run_id: tmp_path / run_id)
    code = (
        "import cadquery as cq\n"
        "body = cq.Workplane('XY').cylinder(100, 40).translate((0, 0, 50))\n"
        "void = cq.Workplane('XY').cylinder(60, 30).translate((0, 0, 50))\n"
        "result = body.cut(void)\n"
    )
    out = execute_cadquery(code, "topo_void")
    assert out.get("success") is False, out
    assert out.get("num_solids") == 1
    assert (out.get("num_shells") or 0) > 1
    err = str(out.get("error", ""))
    assert "shell" in err.lower()
    assert "CAUSE" in err
    assert "TOUCH" not in err
