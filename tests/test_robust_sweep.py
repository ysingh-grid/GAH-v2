"""
Robust swept construction + universal unsound-geometry diagnostic (deterministic).

Swept self-intersection on a sharp bend is the dominant swept-geometry failure (a legal plan that
builds an unsound solid, forcing trial-and-error). The kernel now: (1) tries a rounded transition +
a light corner-round and PREFERS a candidate that meshes sound, FAITHFUL-FIRST so an already-sound
sweep is unchanged (no regression) and an alternative is used only if it is sound (never worse than
plain); (2) when a swept/lofted/revolved part is still unsound (e.g. a tube genuinely fatter than
its turn — which NO corner treatment can save), verify names the SPECIFIC cause + fix instead of a
raw triangle count.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))
os.environ.setdefault("PRIMITIVES_JSON_DATA", (ROOT / "schemas" / "primitives.json").read_text())

import cadquery as cq              # noqa: E402
import kernel                      # noqa: E402
import verify as verify_mod        # noqa: E402

_SMOOTH = [[0, 0, 0], [0, 0, 10], [20, 0, 15], [100, 0, 10], [200, 0, 0], [250, 0, -5]]   # step-31 PASS
_SHARP = [[0, 0, 0], [0, 0, 5], [75, 0, 5], [175, 0, -5], [225, 0, -10]]                  # step-30 FAIL


def _sound(sol):
    m = verify_mod.cq_to_meshlib(sol)
    meas = verify_mod.measure(m)
    return bool(meas["watertight"]), int(meas["self_intersections"])


def test_smooth_sweep_stays_sound_no_regression():
    sol = kernel._primitive_solid("swept_circle", {"radius": 6.0, "path": _SMOOTH})
    wt, si = _sound(sol)
    assert wt and si == 0, f"a previously-sound sweep must stay sound, got watertight={wt} self_int={si}"
    print("PASS smooth swept_circle stays sound (no regression)")


def test_robust_sweep_never_worse_than_plain():
    # The robust helper must NEVER increase self-intersections vs the plain sweep (soundness-gated).
    plain = cq.Workplane("XY").circle(10.0).sweep(
        cq.Workplane("XY").polyline([tuple(p) for p in _SHARP]), multisection=False)
    _, si_plain = _sound(plain)
    robust = kernel._primitive_solid("swept_circle", {"radius": 10.0, "path": _SHARP})
    _, si_robust = _sound(robust)
    assert si_robust <= si_plain, f"robust sweep worse than plain: robust={si_robust} > plain={si_plain}"
    print(f"PASS robust sweep never worse than plain (robust={si_robust} <= plain={si_plain})")


def test_ill_posed_sweep_gets_specific_diagnostic():
    # A tube of radius 10 on a 5mm first segment is genuinely ill-posed — no corner treatment can
    # fix it. It must FAIL verify AND the failure detail must NAME the swept cause + the real fix.
    plan = {"title": "Sharp Arm", "assembly_kind": "single_solid",
            "overall_dimensions": {"width": 300, "length": 50, "height": 50},
            "engineering_requirements": {"functional": [], "environmental_thermal": [],
                                         "structural": [], "manufacturing_cost": []},
            "assumptions": [], "clarifications": [],
            "primitives_sequence": [{"sequence_id": 1, "name": "arm", "primitive_type": "swept_circle",
                                     "parameters": {"radius": 10.0, "path": _SHARP}, "operation": "new",
                                     "rationale": "a deliberately ill-posed sharp swept arm for the diagnostic"}]}
    res = kernel.build_plan(plan)
    assert res["ok"], res
    rep = verify_mod.verify_solid(res["solid"], plan=plan)
    assert rep["verdict"] == "FAIL", rep
    detail = " ".join(c["detail"] for c in rep["checks"] if not c["passed"]).lower()
    assert "sweep" in detail and ("reduce the radius" in detail or "too large" in detail), detail
    print("PASS ill-posed sweep FAILS with a SPECIFIC swept self-intersection diagnostic")


if __name__ == "__main__":
    test_smooth_sweep_stays_sound_no_regression()
    test_robust_sweep_never_worse_than_plain()
    test_ill_posed_sweep_gets_specific_diagnostic()
    print("\nALL robust-sweep tests passed.")
