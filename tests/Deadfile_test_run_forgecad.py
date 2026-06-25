"""Tests for tools/run_forgecad.py — forgecad CLI wrapper."""

from __future__ import annotations

import shutil
from unittest.mock import patch

import pytest

from tools.run_forgecad import run_forgecad


def test_forgecad_not_installed_returns_error(tmp_path) -> None:
    """When forgecad binary is missing, run_forgecad returns success=False."""
    import shutil as _shutil

    from tools.artifacts import new_run_id

    run_id = new_run_id("test_no_cli")
    try:
        with patch("tools.run_forgecad._FORGECAD_CMD", "__nonexistent_cmd__"):
            result = run_forgecad("dummy.forge.js", run_id)
        assert result["success"] is False
        assert result["stl_path"] is None
        assert result["error"] is not None
    finally:
        import pathlib
        _shutil.rmtree(pathlib.Path("outputs") / run_id, ignore_errors=True)


def test_bad_js_returns_error(tmp_path) -> None:
    """A .forge.js with syntax errors causes success=False via forgecad run."""
    if not shutil.which("forgecad"):
        pytest.skip("forgecad CLI not installed")

    import shutil as _shutil

    from tools.artifacts import new_run_id

    bad_js = tmp_path / "bad.forge.js"
    bad_js.write_text("THIS IS NOT VALID JS @@@@", encoding="utf-8")

    run_id = new_run_id("test_bad_js")
    try:
        result = run_forgecad(str(bad_js), run_id)
        assert result["success"] is False
        assert result["error"] is not None
    finally:
        import pathlib
        _shutil.rmtree(pathlib.Path("outputs") / run_id, ignore_errors=True)


@pytest.mark.skipif(
    not shutil.which("forgecad"),
    reason="forgecad CLI not installed",
)
def test_forgecad_run_validates_without_auth(tmp_path) -> None:
    """forgecad run (validation only) works without FORGECAD_TOKEN."""
    import subprocess

    from runtime.compile_forge import compile_plan_to_forge
    from runtime.schema import Operation, PrimitivePlan, PrimitiveStep, load_library

    library = load_library()
    plan = PrimitivePlan(
        part_name="auth_test",
        steps=[
            PrimitiveStep(
                id="b", primitive="box", operation=Operation.base,
                parameters={"length": 5.0, "width": 5.0, "height": 5.0},
            )
        ],
    )
    js = compile_plan_to_forge(plan, library)
    forge_file = tmp_path / "auth_test.forge.js"
    forge_file.write_text(js, encoding="utf-8")
    result = subprocess.run(  # noqa: S603
        ["forgecad", "run", str(forge_file)],  # noqa: S607
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"forgecad run failed:\n{result.stderr}"


@pytest.mark.skipif(
    not shutil.which("forgecad") or not __import__("os").environ.get("FORGECAD_TOKEN"),
    reason="forgecad CLI not installed or FORGECAD_TOKEN not set (export requires auth)",
)
def test_valid_box_script_succeeds(tmp_path) -> None:
    """A valid box .forge.js succeeds: validate + STL export pass (needs FORGECAD_TOKEN)."""
    import shutil as _shutil

    from runtime.compile_forge import compile_plan_to_forge
    from runtime.schema import (
        Operation,
        PrimitivePlan,
        PrimitiveStep,
        load_library,
    )
    from tools.artifacts import new_run_id

    library = load_library()
    plan = PrimitivePlan(
        part_name="box_test",
        steps=[
            PrimitiveStep(
                id="base",
                primitive="box",
                operation=Operation.base,
                parameters={"length": 10.0, "width": 10.0, "height": 10.0},
            )
        ],
    )
    js = compile_plan_to_forge(plan, library)
    forge_file = tmp_path / "box_test.forge.js"
    forge_file.write_text(js, encoding="utf-8")

    run_id = new_run_id("test_box_forge")
    try:
        result = run_forgecad(str(forge_file), run_id)
        assert result["success"] is True, f"Expected success, got error: {result['error']}"
        assert result["stl_path"] is not None
        import os
        assert os.path.exists(result["stl_path"])
        assert result["compare_score"] is None  # no reference STL provided
    finally:
        _shutil.rmtree(f"outputs/{run_id}", ignore_errors=True)
