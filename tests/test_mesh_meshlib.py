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


# ── expected_components: legal multi-body compounds ─────────────────────────
# Live bug: `passes` hardcoded num_components == 1, so every legal multi-body
# plan (playbook: "a union of disjoint solids is legal; it produces one
# multi-component compound") failed inspection, repair correctly found nothing
# to fix, and the run burned its whole replan budget on a valid model. Ground
# truth is the B-rep shell count (execution_result["shells_count"]): 1 shell =
# 1 mesh component, verified for plain solids, disjoint compounds, and closed
# hollow parts (outer + cavity = 2).


def _two_disjoint_cubes(path) -> None:
    a = mr.makeCube()
    b = mr.makeCube()
    xf = mr.AffineXf3f.translation(mr.Vector3f(10.0, 0.0, 0.0))
    b.transform(xf)
    a.addMesh(b)
    mr.saveMesh(a, str(path))


def test_inspect_multibody_passes_with_expected_components(tmp_path):
    stl = tmp_path / "two.stl"
    _two_disjoint_cubes(stl)
    report = inspect_mesh(str(stl), expected_components=2)
    assert report["success"]
    assert report["num_components"] == 2
    assert report["expected_components"] == 2
    assert report["passes"]


def test_inspect_multibody_fails_when_single_body_expected(tmp_path):
    """Unexpected extra components (features that only touch instead of
    overlapping) must still fail — only DECLARED multi-body geometry passes."""
    stl = tmp_path / "two.stl"
    _two_disjoint_cubes(stl)
    report = inspect_mesh(str(stl))  # default expected_components=1
    assert not report["passes"]


def test_execute_reports_shells_count_for_multibody():
    pytest.importorskip("cadquery")
    from runtime import schema
    from runtime.compile_cadquery import compile_plan_to_cadquery
    from runtime.schema import plan_from_dict
    from tools.artifacts import new_run_id, run_dir
    from tools.execute_cadquery import execute_cadquery

    plan = plan_from_dict(
        {
            "part_name": "two_bodies",
            "steps": [
                {
                    "id": "a", "primitive": "box", "operation": "base",
                    "parameters": {"length": 10.0, "width": 10.0, "height": 10.0},
                    "position": [0, 0, 0],
                },
                {
                    "id": "b", "primitive": "box", "operation": "union",
                    "parameters": {"length": 10.0, "width": 10.0, "height": 10.0},
                    "position": [50, 0, 0],
                },
            ],
        }
    )
    run_id = new_run_id("test_shells")
    try:
        code = compile_plan_to_cadquery(plan, schema.load_library())
        ex = execute_cadquery(code, run_id)
        assert ex["success"], ex.get("error")
        assert ex["shells_count"] == 2
        report = inspect_mesh(ex["stl_path"], ex["shells_count"])
        assert report["passes"], report
    finally:
        shutil.rmtree(run_dir(run_id), ignore_errors=True)


# ── reject-if-worse guard ────────────────────────────────────────────────────
# Live bug: the voxel self-intersection remesh returned meshes at +151% volume
# / 54 components (was 3) and -8.3% volume with 2/3 of the faces stripped, and
# those butchered meshes were what got rendered and judged. A repair that
# degrades the mesh must be rejected, its file deleted, and the failure routed
# to the replanner as a PLAN problem.


def test_repair_rejected_when_it_degrades_the_mesh(tmp_path, monkeypatch):
    """Simulate the live degradation: force the post-repair inspection to see a
    ballooned, shattered mesh and assert the guard fires + deletes the file."""
    import os
    import sys

    rm = sys.modules["tools.repair_mesh"]
    from tools.artifacts import new_run_id, run_dir

    stl = tmp_path / "open.stl"
    _save_open_cube(stl)

    real_inspect = inspect_mesh

    def fake_after_inspect(path, expected_components=1):
        report = real_inspect(path, expected_components)
        report["volume_mm3"] = report["volume_mm3"] * 2.5   # +150% drift
        report["num_components"] = 54                        # shattered
        report["passes"] = False
        return report

    # tools/__init__.py rebinds `inspect_mesh`/`repair_mesh` on the package to
    # the FUNCTIONS, shadowing the submodules (same trap documented in
    # test_execute_cadquery.py) — pull the real module objects from sys.modules.
    im = sys.modules["tools.inspect_mesh"]
    monkeypatch.setattr(im, "inspect_mesh", fake_after_inspect)

    run_id = new_run_id("test_reject_worse")
    try:
        result = rm.repair_mesh(str(stl), run_id, expected_components=1)
        assert result["success"]
        assert result["passes"] is False
        assert result["rejected"], result
        assert any("volume drifted" in r for r in result["rejected"])
        assert any("shattered" in r for r in result["rejected"])
        assert "repaired_stl_path" not in result
        assert not os.path.exists(
            os.path.join(str(run_dir(run_id)), "solid_repaired.stl")
        )
        assert "fix the PLAN" in result["error"]
    finally:
        _cleanup(run_id)


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
