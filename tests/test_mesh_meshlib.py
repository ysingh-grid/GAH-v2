"""M5: MeshLib inspect + repair (no trimesh fallback).

Watertight and deliberately-open meshes are built with MeshLib itself; a final
case runs the real compile -> execute -> inspect path end to end.
"""

import shutil

import pytest

mr = pytest.importorskip("meshlib.mrmeshpy")

from tools.inspect_mesh import inspect_mesh  # noqa: E402
from tools.repair_mesh import repair_mesh  # noqa: E402


def _save_cube(path) -> None:
    mr.saveMesh(mr.makeCube(), str(path))


def _save_open_cube(path) -> None:
    mesh = mr.makeCube()
    first_face = next(iter(mesh.topology.getValidFaces()))
    mesh.topology.deleteFace(first_face)
    mr.saveMesh(mesh, str(path))


# ── inspect ──────────────────────────────────────────────────────────────────


def test_inspect_watertight_cube_passes(tmp_path):
    stl = tmp_path / "cube.stl"
    _save_cube(stl)
    report = inspect_mesh(str(stl))
    assert report["success"]
    assert report["is_watertight"]
    assert report["open_holes"] == 0
    assert report["num_components"] == 1
    assert report["self_intersections"] == 0
    assert report["passes"]
    assert report["volume_mm3"] > 0


def test_inspect_open_cube_fails(tmp_path):
    stl = tmp_path / "open.stl"
    _save_open_cube(stl)
    report = inspect_mesh(str(stl))
    assert report["success"]
    assert not report["is_watertight"]
    assert report["open_holes"] >= 1
    assert not report["passes"]


def test_inspect_missing_file_returns_failure():
    report = inspect_mesh("/no/such/file.stl")
    assert report["success"] is False
    assert "not found" in report["error"]


# ── repair ───────────────────────────────────────────────────────────────────


def _cleanup(run_id):
    from tools.artifacts import run_dir

    shutil.rmtree(run_dir(run_id), ignore_errors=True)


def test_repair_closes_open_mesh(tmp_path):
    from tools.artifacts import new_run_id

    stl = tmp_path / "open.stl"
    _save_open_cube(stl)
    run_id = new_run_id("test_repair")
    try:
        result = repair_mesh(str(stl), run_id)
        assert result["success"], result.get("error")
        assert result["before"]["open_holes"] >= 1
        assert any("filled" in a for a in result["actions"])
        assert result["after"]["is_watertight"]
        assert result["passes"]
    finally:
        _cleanup(run_id)


def test_repair_clean_mesh_reports_no_repair_needed(tmp_path):
    from tools.artifacts import new_run_id

    stl = tmp_path / "cube.stl"
    _save_cube(stl)
    run_id = new_run_id("test_repair_clean")
    try:
        result = repair_mesh(str(stl), run_id)
        assert result["success"]
        assert result["actions"] == ["no repair needed (already clean)"]
        assert result["passes"]
    finally:
        _cleanup(run_id)


# ── end-to-end: compile -> execute -> inspect ────────────────────────────────


def test_compiled_cube_stl_inspects_clean():
    pytest.importorskip("cadquery")
    from runtime import schema
    from runtime.compile_cadquery import compile_plan_to_cadquery
    from runtime.schema import plan_from_dict
    from tools.artifacts import new_run_id, run_dir
    from tools.execute_cadquery import execute_cadquery

    plan = plan_from_dict(
        {
            "part_name": "cube",
            "steps": [
                {
                    "id": "body",
                    "primitive": "box",
                    "operation": "base",
                    "parameters": {"length": 30.0, "width": 30.0, "height": 30.0},
                }
            ],
        }
    )
    run_id = new_run_id("test_e2e_mesh")
    try:
        code = compile_plan_to_cadquery(plan, schema.load_library())
        ex = execute_cadquery(code, run_id)
        assert ex["success"], ex.get("error")
        report = inspect_mesh(ex["stl_path"])
        assert report["success"], report.get("error")
        assert report["is_watertight"]
        assert report["passes"]
    finally:
        shutil.rmtree(run_dir(run_id), ignore_errors=True)
