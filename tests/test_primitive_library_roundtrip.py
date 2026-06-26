"""Per-primitive round-trip gate: every library primitive must survive BOTH compilers.

Motivation: a primitive can compile fine on one path and be silently broken on the
other. `rounded_cylinder` passed CadQuery but its forge.js threw at runtime —
caught only by *running* the JS. This suite parametrizes over every primitive in
library.json and asserts three things, escalating in rigor:

  1. CadQuery: compile -> execute -> a real solid with volume > 0.
  2. ForgeCAD: the forge_template compiles to a non-empty .forge.js string.
  3. ForgeCAD (live, when the `forgecad` CLI is installed): the JS actually RUNS,
     exports an STL, and that STL matches the CadQuery STL via `forgecad compare 3d`
     above a similarity threshold — the real "both compilers agree" gate.

Leg 3 skips automatically where the CLI is absent (e.g. the python-only worker
image); legs 1-2 run everywhere. When adding a new primitive, this is the gate it
must pass before it is trusted.
"""

import shutil

import pytest

from runtime import schema
from runtime.compile_cadquery import CompileError, compile_plan_to_cadquery
from runtime.Deadfile_compile_forge import CompileForgeError, compile_plan_to_forge
from runtime.schema import plan_from_dict

LIBRARY = schema.load_library()
PRIMITIVE_NAMES = sorted(LIBRARY)

# Cross-compiler agreement tolerances, measured neutrally with MeshLib (NOT
# forgecad's own `compare 3d`, whose surface F-score false-fails correct shapes —
# it scored an identical-volume box at 38%). Volume alone is too weak: two solids
# can have equal volume but different SHAPE or ORIENTATION (a horizontal vs
# vertical cylinder). So we also gate the bounding box — its size (catches
# orientation/shape) and its center (catches differing intrinsic origins, e.g.
# CadQuery centers a box at Z=0 while forge sat it base-at-origin).
_MAX_VOL_DIFF_PCT = 2.0
_MAX_BBOX_MM = 0.5  # max per-axis difference in bbox size OR center, in mm
# Even volume AND bbox can both match while the shape differs (a wedge sloping the
# wrong way, a polygon rotated by one step). The decisive gate is the symmetric
# Hausdorff distance — the farthest any surface point of one solid sits from the
# other. Legit rounded-edge tessellation differences sit ~0.45mm; real shape/
# orientation errors are >0.7mm, so 0.6mm separates them.
_MAX_HAUSDORFF_MM = 0.6
_KNOWN_DIVERGENT: dict[str, str] = {}


def _one_step_plan(name: str):
    """A minimal single-step plan that builds `name` from its library defaults."""
    return plan_from_dict(
        {"part_name": name, "steps": [{"id": "s", "primitive": name, "operation": "base"}]}
    )


@pytest.fixture
def _cadquery_available():
    return pytest.importorskip("cadquery")


# ── Leg 1: CadQuery compile + execute ─────────────────────────────────────────
@pytest.mark.parametrize("name", PRIMITIVE_NAMES)
def test_primitive_executes_in_cadquery(name, _cadquery_available):
    from tools.artifacts import new_run_id, run_dir
    from tools.execute_cadquery import execute_cadquery

    run_id = new_run_id(f"rt_cq_{name}")
    try:
        code = compile_plan_to_cadquery(_one_step_plan(name), LIBRARY)
        result = execute_cadquery(code, run_id)
    except CompileError as exc:
        pytest.fail(f"{name}: CadQuery compile failed: {exc}")
    finally:
        shutil.rmtree(run_dir(run_id), ignore_errors=True)

    assert result["success"], f"{name}: execute failed: {result.get('error')}"
    assert result["volume"] > 0, f"{name}: degenerate solid (volume {result['volume']})"


# ── Leg 2: ForgeCAD compile (pure, no CLI) ────────────────────────────────────
@pytest.mark.skip(reason="ForgeCAD removed in scope reduction")
@pytest.mark.parametrize("name", PRIMITIVE_NAMES)
def test_primitive_compiles_to_forge(name):
    try:
        js = compile_plan_to_forge(_one_step_plan(name), LIBRARY)
    except CompileForgeError as exc:
        pytest.fail(f"{name}: forge compile failed: {exc}")
    assert js.strip(), f"{name}: empty forge.js"
    assert "return" in js, f"{name}: forge.js has no return statement"


# ── Leg 3: ForgeCAD live run + neutral volume match vs CadQuery (needs the CLI) ─
@pytest.mark.skip(reason="ForgeCAD removed in scope reduction")
@pytest.mark.parametrize("name", PRIMITIVE_NAMES)
def test_primitive_forge_matches_cadquery(name, _cadquery_available):
    if name in _KNOWN_DIVERGENT:
        pytest.xfail(_KNOWN_DIVERGENT[name])

    from tools.artifacts import new_run_id, run_dir
    from tools.execute_cadquery import execute_cadquery
    from tools.inspect_mesh import inspect_mesh
    from tools.run_forgecad import run_forgecad

    run_id = new_run_id(f"rt_fc_{name}")
    rdir = run_dir(run_id)
    try:
        # CadQuery reference solid.
        cq = execute_cadquery(compile_plan_to_cadquery(_one_step_plan(name), LIBRARY), run_id)
        assert cq["success"], f"{name}: CadQuery reference failed: {cq.get('error')}"

        # Run the forge.js for real and export its STL (no compare-score gate).
        forge_path = rdir / "model.forge.js"
        forge_path.write_text(
            compile_plan_to_forge(_one_step_plan(name), LIBRARY), encoding="utf-8"
        )
        out = run_forgecad(str(forge_path), run_id)
        assert out["success"], f"{name}: forgecad run/export failed: {out.get('error')}"

        cq_mesh = inspect_mesh(cq["stl_path"])
        fg_mesh = inspect_mesh(out["stl_path"])

        # Hausdorff must be read before the STLs are cleaned up below.
        import math

        import meshlib.mrmeshpy as mr

        hausdorff = math.sqrt(
            mr.findMaxDistanceSq(mr.loadMesh(cq["stl_path"]), mr.loadMesh(out["stl_path"]))
        )
    finally:
        shutil.rmtree(rdir, ignore_errors=True)

    assert cq_mesh.get("is_watertight"), f"{name}: CadQuery STL not watertight"
    assert fg_mesh.get("is_watertight"), f"{name}: forge STL not watertight"

    # 1) Volume.
    cv, fv = cq_mesh["volume_mm3"], fg_mesh["volume_mm3"]
    diff = abs(cv - fv) / cv * 100
    assert diff <= _MAX_VOL_DIFF_PCT, (
        f"{name}: forge volume {fv:.2f} vs CadQuery {cv:.2f} = {diff:.2f}% "
        f"(max {_MAX_VOL_DIFF_PCT}%)"
    )

    # 2) Bounding box — size (shape/orientation) and center (intrinsic origin).
    cb, fb = cq_mesh["bbox"], fg_mesh["bbox"]
    axes = (("xmin", "xmax"), ("ymin", "ymax"), ("zmin", "zmax"))
    cq_size = [cb[hi] - cb[lo] for lo, hi in axes]
    fg_size = [fb[hi] - fb[lo] for lo, hi in axes]
    cq_center = [(cb[lo] + cb[hi]) / 2 for lo, hi in axes]
    fg_center = [(fb[lo] + fb[hi]) / 2 for lo, hi in axes]

    size_off = [abs(a - b) for a, b in zip(cq_size, fg_size)]
    center_off = [abs(a - b) for a, b in zip(cq_center, fg_center)]
    assert max(size_off) <= _MAX_BBOX_MM, (
        f"{name}: bbox SIZE mismatch (shape/orientation) — "
        f"CQ {[round(v, 2) for v in cq_size]} vs forge {[round(v, 2) for v in fg_size]}"
    )
    assert max(center_off) <= _MAX_BBOX_MM, (
        f"{name}: bbox CENTER mismatch (intrinsic origin) — "
        f"CQ {[round(v, 2) for v in cq_center]} vs forge {[round(v, 2) for v in fg_center]}"
    )

    # 3) Hausdorff — catches shape/orientation errors volume and bbox both miss.
    assert hausdorff <= _MAX_HAUSDORFF_MM, (
        f"{name}: forge vs CadQuery Hausdorff distance {hausdorff:.3f}mm "
        f"(max {_MAX_HAUSDORFF_MM}mm) — shapes differ despite matching volume/bbox"
    )
    