"""
Task 5 (deterministic): fast custom-code API lint + auto-RAG.

The failing run's step 28 wrote `result.faces(">Z").taper(15)` (no such method) and only learned so
AFTER a full build returned `'Workplane' object has no attribute 'taper'`. The linter must catch
this BEFORE the build with a precise correction + KB example; valid code must pass untouched; and a
linter bug must never block a build (fail-open).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))

from cad_kernel import cq_lint
from cad_kernel import kernel


def test_lint_catches_taper_with_correction():
    code = ('import cadquery as cq\n'
            'result = cq.Workplane("XY").box(450, 60, 700, centered=(True, True, False))\n'
            'result = result.faces(">Z").taper(15)\n'
            'result = result.edges("|Z").fillet(29.9)')
    err = cq_lint.lint_code_sketch(code, cadquery_operations=["box", "taper", "fillet"])
    assert err, "lint must flag the invented taper() method"
    assert "taper" in err and "loft" in err.lower(), err
    print("PASS lint catches taper() pre-build with the correct loft alternative")


def test_lint_passes_valid_code():
    code = ('import cadquery as cq\n'
            'result = (cq.Workplane("XY").rect(80, 80).workplane(offset=100).rect(40, 40)'
            '.loft().edges("|Z").fillet(5))')
    err = cq_lint.lint_code_sketch(code, cadquery_operations=["rect", "loft", "fillet"])
    assert err is None, f"valid code must NOT be flagged, got: {err}"
    print("PASS valid loft/fillet code passes the linter untouched")


def test_lint_blocks_at_build():
    # End-to-end: a custom step using taper must fail the kernel build with the precise lint message,
    # BEFORE spawning the subprocess.
    params = {"shape_description": "tapered block",
              "cadquery_operations": ["box", "taper"],
              "code_sketch": 'import cadquery as cq\nresult = cq.Workplane("XY").box(10,10,10).faces(">Z").taper(5)',
              "declared_dimensions": {}}
    plan = {"title": "t", "assembly_kind": "single_solid",
            "overall_dimensions": {"width": 10, "length": 10, "height": 10},
            "engineering_requirements": {"functional": [], "environmental_thermal": [],
                                         "structural": [], "manufacturing_cost": []},
            "assumptions": [], "clarifications": [],
            "primitives_sequence": [{"sequence_id": 1, "name": "t", "primitive_type": "custom",
                                     "parameters": params, "operation": "new",
                                     "rationale": "a tapered block to exercise the linter end to end"}]}
    res = kernel.build_plan(plan)
    assert not res["ok"], "build must fail on the invented method"
    err = next((s.get("error", "") for s in res["steps"] if not s.get("ok")), "")
    assert "taper" in err and "DO NOT EXIST" in err, err
    print("PASS kernel build is blocked pre-subprocess with the precise lint correction")


def test_lint_fail_open(monkeypatch=None):
    # If the universe introspection blows up, lint must return None (never block).
    import cad_kernel.cq_lint as L
    orig = L._cq_method_universe
    L._cq_method_universe = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        assert L.lint_code_sketch("result = cq.Workplane('XY').taper(1)", ["taper"]) is None
        print("PASS linter fails open (internal error never blocks a build)")
    finally:
        L._cq_method_universe = orig


if __name__ == "__main__":
    test_lint_catches_taper_with_correction()
    test_lint_passes_valid_code()
    test_lint_blocks_at_build()
    test_lint_fail_open()
    print("\nALL custom-code lint tests passed.")
