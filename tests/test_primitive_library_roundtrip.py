"""Per-primitive round-trip gate: every library primitive must compile + execute.

Parametrizes over every primitive in library.json and asserts the CadQuery path:
compile -> execute -> a real solid with volume > 0. When adding a new primitive,
this is the gate it must pass before it is trusted.

(The old ForgeCAD legs — pure forge-compile + live `forgecad compare 3d` vs the
CadQuery STL — were removed with the forge compiler in the scope reduction. The
deterministic CadQuery compiler is now the single target.)
"""

import shutil

import pytest

from runtime import schema
from runtime.compile_cadquery import CompileError, compile_plan_to_cadquery
from runtime.schema import plan_from_dict

LIBRARY = schema.load_library()
PRIMITIVE_NAMES = sorted(LIBRARY)


def _one_step_plan(name: str):
    """A minimal single-step plan that builds `name` from its library defaults."""
    return plan_from_dict(
        {"part_name": name, "steps": [{"id": "s", "primitive": name, "operation": "base"}]}
    )


@pytest.fixture
def _cadquery_available():
    return pytest.importorskip("cadquery")


# ── CadQuery compile + execute ────────────────────────────────────────────────
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
