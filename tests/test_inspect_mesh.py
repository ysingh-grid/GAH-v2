"""Guard tests for the mesh-validity gate.

`num_components == 1` is a HARD gate and must never be demoted to a soft/VLM
signal: a render can hide a 2-piece defect (a cap resting on a bottle looks
fused but is a loose part). These tests pin that the gate rejects any mesh that
is not a single watertight, self-intersection-free component. They exercise the
pure `mesh_passes` predicate, so they need no MeshLib / real geometry.
"""

from __future__ import annotations

from tools.inspect_mesh import mesh_passes


def test_mesh_passes_only_for_single_watertight_clean_component():
    assert mesh_passes(is_watertight=True, self_intersections=0, num_components=1) is True


def test_two_components_never_pass_even_when_otherwise_clean():
    # The honest gate: a watertight, hole-free, self-intersection-free mesh that
    # is TWO solids (e.g. a bottle + a non-fused cap) must still FAIL.
    assert mesh_passes(is_watertight=True, self_intersections=0, num_components=2) is False


def test_non_watertight_fails():
    assert mesh_passes(is_watertight=False, self_intersections=0, num_components=1) is False


def test_self_intersections_fail():
    assert mesh_passes(is_watertight=True, self_intersections=3, num_components=1) is False
