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
    