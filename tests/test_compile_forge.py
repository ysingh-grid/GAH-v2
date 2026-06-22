"""Real-world tests for runtime/compile_forge.py — plan -> editable .forge.js."""

from __future__ import annotations

import shutil

import pytest

from runtime.compile_forge import CompileForgeError, compile_plan_to_forge
from runtime.schema import (
    Operation,
    Pattern,
    PatternType,
    PrimitivePlan,
    PrimitiveStep,
    load_library,
)
from tests.real_world_scenarios import mounting_plate_with_four_holes, open_electronics_enclosure


@pytest.fixture(scope="module")
def library() -> dict:
    return load_library()


def _box_plan(part_name: str = "test_box") -> PrimitivePlan:
    return PrimitivePlan(
        part_name=part_name,
        steps=[
            PrimitiveStep(
                id="base",
                primitive="box",
                operation=Operation.base,
                parameters={"length": 10.0, "width": 10.0, "height": 10.0},
            )
        ],
    )


# ── Template filling ──────────────────────────────────────────────────────────

def test_box_emits_forge_call(library: dict) -> None:
    js = compile_plan_to_forge(_box_plan(), library)
    assert "box(10.0, 10.0, 10.0)" in js


def test_cylinder_uses_height_then_radius(library: dict) -> None:
    plan = PrimitivePlan(
        part_name="cyl",
        steps=[
            PrimitiveStep(
                id="b",
                primitive="cylinder",
                operation=Operation.base,
                parameters={"radius": 5.0, "height": 20.0},
            )
        ],
    )
    js = compile_plan_to_forge(plan, library)
    assert "cylinder(20.0, 5.0)" in js


def test_cone_uses_base_top_radii(library: dict) -> None:
    plan = PrimitivePlan(
        part_name="cone",
        steps=[
            PrimitiveStep(
                id="b",
                primitive="cone",
                operation=Operation.base,
                parameters={"base_diameter": 20.0, "top_diameter": 0.0, "height": 15.0},
            )
        ],
    )
    js = compile_plan_to_forge(plan, library)
    assert "cylinder(15.0, 20.0/2.0, 0.0/2.0)" in js


def test_profile_extrude_passes_list(library: dict) -> None:
    plan = PrimitivePlan(
        part_name="prof",
        steps=[
            PrimitiveStep(
                id="b",
                primitive="profile_extrude",
                operation=Operation.base,
                parameters={"profile": [[0.0, 0.0], [5.0, 0.0], [0.0, 5.0]], "height": 3.0},
            )
        ],
    )
    js = compile_plan_to_forge(plan, library)
    assert "polygon(" in js
    assert ".extrude(3.0)" in js


def test_revolve_emits_revolve_call(library: dict) -> None:
    plan = PrimitivePlan(
        part_name="rev",
        steps=[
            PrimitiveStep(
                id="b",
                primitive="revolve",
                operation=Operation.base,
                parameters={
                    "profile": [[0.0, 0.0], [5.0, 0.0], [5.0, 10.0], [0.0, 10.0]],
                    "angle": 360.0,
                },
            )
        ],
    )
    js = compile_plan_to_forge(plan, library)
    assert ".revolve(360.0)" in js


# ── CSG operations ────────────────────────────────────────────────────────────

def test_union_emits_add(library: dict) -> None:
    plan = PrimitivePlan(
        part_name="union_test",
        steps=[
            PrimitiveStep(id="base", primitive="box", operation=Operation.base,
                          parameters={"length": 20.0, "width": 20.0, "height": 5.0}),
            PrimitiveStep(id="peg", primitive="cylinder", operation=Operation.union,
                          parameters={"radius": 3.0, "height": 10.0}),
        ],
    )
    js = compile_plan_to_forge(plan, library)
    assert "result.add(s1)" in js


def test_cut_emits_subtract(library: dict) -> None:
    plan = PrimitivePlan(
        part_name="cut_test",
        steps=[
            PrimitiveStep(id="base", primitive="box", operation=Operation.base,
                          parameters={"length": 20.0, "width": 20.0, "height": 10.0}),
            PrimitiveStep(id="hole", primitive="cylinder", operation=Operation.cut,
                          parameters={"radius": 3.0, "height": 12.0}),
        ],
    )
    js = compile_plan_to_forge(plan, library)
    assert "result.subtract(s1)" in js


def test_mounting_plate_handoff_preserves_corner_hole_operations(library: dict) -> None:
    scenario = mounting_plate_with_four_holes()
    js = compile_plan_to_forge(scenario.plan, library)
    assert "electronics_mounting_plate" in js
    assert "_linear(s1, 2," in js
    assert "_linear(s2, 2," in js
    assert js.count("result = result.subtract") == 2


def test_open_enclosure_handoff_preserves_bosses_and_holes(library: dict) -> None:
    scenario = open_electronics_enclosure()
    js = compile_plan_to_forge(scenario.plan, library)
    assert "open_electronics_enclosure" in js
    assert js.count("result = result.add") == 4
    assert js.count("result = result.subtract") == 2


# ── Placement ─────────────────────────────────────────────────────────────────

def test_place_call_emitted(library: dict) -> None:
    plan = PrimitivePlan(
        part_name="placed",
        steps=[
            PrimitiveStep(id="b", primitive="box", operation=Operation.base,
                          parameters={"length": 5.0, "width": 5.0, "height": 5.0},
                          position=(10.0, 0.0, 5.0)),
        ],
    )
    js = compile_plan_to_forge(plan, library)
    assert "_place(s0, 10.0, 0.0, 5.0," in js


# ── Pattern emission ──────────────────────────────────────────────────────────

def test_polar_pattern_emits_polar_helper(library: dict) -> None:
    plan = PrimitivePlan(
        part_name="polar_test",
        steps=[
            PrimitiveStep(id="base", primitive="box", operation=Operation.base,
                          parameters={"length": 20.0, "width": 20.0, "height": 5.0}),
            PrimitiveStep(
                id="pegs",
                primitive="cylinder",
                operation=Operation.union,
                parameters={"radius": 2.0, "height": 5.0},
                position=(8.0, 0.0, 0.0),
                pattern=Pattern(type=PatternType.polar, count=6),
            ),
        ],
    )
    js = compile_plan_to_forge(plan, library)
    assert "_polar(s1, 6," in js


def test_linear_pattern_emits_linear_helper(library: dict) -> None:
    plan = PrimitivePlan(
        part_name="linear_test",
        steps=[
            PrimitiveStep(id="base", primitive="box", operation=Operation.base,
                          parameters={"length": 50.0, "width": 10.0, "height": 5.0}),
            PrimitiveStep(
                id="slots",
                primitive="cylinder",
                operation=Operation.cut,
                parameters={"radius": 2.0, "height": 7.0},
                pattern=Pattern(
                    type=PatternType.linear,
                    count=4,
                    spacing=(10.0, 0.0, 0.0),
                ),
            ),
        ],
    )
    js = compile_plan_to_forge(plan, library)
    assert "_linear(s1, 4," in js


# ── Error cases ───────────────────────────────────────────────────────────────

def test_missing_primitive_raises(library: dict) -> None:
    plan = PrimitivePlan(
        part_name="bad",
        steps=[
            PrimitiveStep(id="b", primitive="nonexistent_shape", operation=Operation.base)
        ],
    )
    with pytest.raises(CompileForgeError, match="primitive_gap"):
        compile_plan_to_forge(plan, library)


def test_missing_forge_template_raises() -> None:
    fake_library = {
        "box_no_forge": {
            "name": "box_no_forge",
            "parameters": {
                "length": {"type": "float", "default": 10.0},
            },
            "template": "cq.Workplane('XY').box({length}, 10, 10)",
            # No forge_template key
        }
    }
    plan = PrimitivePlan(
        part_name="no_forge",
        steps=[
            PrimitiveStep(id="b", primitive="box_no_forge", operation=Operation.base)
        ],
    )
    with pytest.raises(CompileForgeError, match="forge_template"):
        compile_plan_to_forge(plan, fake_library)


# ── Output structure ──────────────────────────────────────────────────────────

def test_output_contains_return_statement(library: dict) -> None:
    js = compile_plan_to_forge(_box_plan("my_part"), library)
    assert 'return { "my_part": result };' in js


def test_output_contains_preamble_helpers(library: dict) -> None:
    js = compile_plan_to_forge(_box_plan(), library)
    assert "function _place(" in js
    assert "function _polar(" in js
    assert "function _linear(" in js
    assert "function _torus(" in js
    assert "function _ellipsoid(" in js
    assert "function _wedge(" in js


def test_all_primitives_have_forge_template(library: dict) -> None:
    missing = [
        name for name, spec in library.items() if not spec.get("forge_template")
    ]
    assert missing == [], f"primitives missing forge_template: {missing}"


# ── Live forgecad run (skipped without CLI) ───────────────────────────────────

@pytest.mark.skipif(
    not shutil.which("forgecad"),
    reason="forgecad CLI not installed",
)
def test_generated_js_passes_forgecad_run(library: dict, tmp_path) -> None:
    """Smoke test: generated box .forge.js must pass `forgecad run`."""
    import subprocess

    js = compile_plan_to_forge(_box_plan("smoke_box"), library)
    forge_file = tmp_path / "smoke_box.forge.js"
    forge_file.write_text(js, encoding="utf-8")
    result = subprocess.run(  # noqa: S603
        ["forgecad", "run", str(forge_file)],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"forgecad run failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
