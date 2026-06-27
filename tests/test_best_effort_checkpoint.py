"""
A4 (deterministic, host-side): when the agent's FINAL is rejected, the pipeline still surfaces the
best REAL artifact instead of nothing — re-build + re-verify the plan, and ONLY if it is sound +
coherent, export it CLEARLY TAGGED 'best-effort, NOT agent-confirmed'. A broken or non-coherent
plan yields nothing. The failure is still raised (best-effort is not a success). Runs offline.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("RLM_MODEL_API_KEY", "dummy")  # orchestrator import requires a key
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import orchestrator as orch


def _reqs():
    return {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []}


def _sound_plan():
    return {
        "title": "best effort box",
        "assembly_kind": "single_solid",
        "overall_dimensions": {"width": 40, "length": 40, "height": 40},
        "engineering_requirements": _reqs(),
        "assumptions": [],
        "primitives_sequence": [
            {"sequence_id": 1, "name": "body", "primitive_type": "box",
             "parameters": {"length": 40, "width": 40, "height": 40}, "operation": "new",
             "rationale": "a single sound box for the best-effort salvage test"},
        ],
    }


def _noncoherent_plan():
    # Two parts placed far apart with no attach -> assembly coherence FAILS -> not salvageable.
    return {
        "title": "disconnected parts",
        "assembly_kind": "assembly",
        "overall_dimensions": {"width": 100, "length": 100, "height": 100},
        "engineering_requirements": _reqs(),
        "assumptions": [],
        "primitives_sequence": [
            {"sequence_id": 1, "name": "a", "primitive_type": "box",
             "parameters": {"length": 20, "width": 20, "height": 20}, "operation": "new",
             "part": "a", "position": [0, 0, 0],
             "rationale": "first isolated part for the non-coherent test"},
            {"sequence_id": 2, "name": "b", "primitive_type": "box",
             "parameters": {"length": 20, "width": 20, "height": 20}, "operation": "new",
             "part": "b", "position": [1000, 0, 0],
             "rationale": "second isolated part placed far away so it cannot touch"},
        ],
    }


def _cleanup(paths):
    for p in paths or []:
        try:
            os.path.exists(p) and os.remove(p)
        except Exception:
            pass


def test_salvage_sound_plan():
    outs = orch._best_effort_salvage(_sound_plan())
    try:
        assert outs, "expected best-effort artifacts for a sound plan"
        assert any("besteffort_" in str(o) for o in outs), outs
        assert all(os.path.exists(o) for o in outs), outs
        print(f"PASS sound plan salvaged -> {len(outs)} best-effort artifact(s), tagged 'besteffort_'")
    finally:
        _cleanup(outs)


def test_noncoherent_not_salvaged():
    outs = orch._best_effort_salvage(_noncoherent_plan())
    assert outs is None, f"expected None (non-coherent must not be salvaged), got {outs}"
    print("PASS non-coherent plan NOT salvaged (returns None)")


def test_broken_plan_not_salvaged():
    assert orch._best_effort_salvage({}) is None
    assert orch._best_effort_salvage({"primitives_sequence": []}) is None
    print("PASS empty/broken plan NOT salvaged (returns None)")


def test_fail_still_raises_but_salvages():
    salvaged = {"paths": None}
    raised = False
    try:
        orch._fail("simulated gate rejection", None, plan_dict=_sound_plan())
    except orch.PipelineError:
        raised = True
    # find + clean the artifact the salvage wrote
    base = ROOT / "exports" / "besteffort_best_effort_box.stl"
    try:
        assert raised, "_fail must still raise PipelineError"
        assert base.exists(), f"_fail should have salvaged a best-effort export at {base}"
        print("PASS _fail still raises PipelineError AND produced a best-effort artifact")
    finally:
        for ext in ("exports/besteffort_best_effort_box.stl",
                    "exports/besteffort_best_effort_box.step",
                    "renders/besteffort_best_effort_box.png"):
            p = ROOT / ext
            try:
                p.exists() and p.unlink()
            except Exception:
                pass


def _write_ckpt(plan, trust_tier="needs_review", rank=1):
    import json, tempfile
    p = tempfile.mktemp(suffix=".forgecad_ckpt.json")
    with open(p, "w") as f:
        json.dump({"rank": rank, "trust_tier": trust_tier, "plan": plan,
                   "measured_bbox": [40, 40, 40], "fidelity": None}, f)
    return p


def _clean_besteffort_box():
    for ext in ("exports/besteffort_best_effort_box.stl",
                "exports/besteffort_best_effort_box.step",
                "renders/besteffort_best_effort_box.png"):
        p = ROOT / ext
        try:
            p.exists() and p.unlink()
        except Exception:
            pass


def test_promote_checkpoint_delivers():
    ckpt = _write_ckpt(_sound_plan(), trust_tier="needs_review")
    outs = orch._promote_best_candidate(ckpt)
    try:
        assert outs, "expected best-effort artifacts promoted from the run checkpoint"
        assert all(os.path.exists(o) for o in outs), outs
        print("PASS checkpoint promotion delivers the best sound candidate")
    finally:
        _cleanup(outs)
        _clean_besteffort_box()
        os.path.exists(ckpt) and os.remove(ckpt)


def test_promote_broken_checkpoint_none():
    ckpt = _write_ckpt(_noncoherent_plan())
    try:
        assert orch._promote_best_candidate(ckpt) is None, "non-coherent checkpoint must not promote"
        print("PASS non-coherent checkpoint promotes nothing")
    finally:
        os.path.exists(ckpt) and os.remove(ckpt)


def test_no_final_still_promotes_checkpoint():
    # THE regression for the latest run: agent never FINAL'd (budget exhaustion), but a sound
    # candidate was banked → the run must STILL deliver it instead of nothing.
    ckpt = _write_ckpt(_sound_plan(), trust_tier="needs_review")
    raised = False
    try:
        orch._fail("The agent did not FINAL a plan dict.", None, checkpoint_path=ckpt)
    except orch.PipelineError:
        raised = True
    base = ROOT / "exports" / "besteffort_best_effort_box.stl"
    try:
        assert raised, "_fail must still raise PipelineError"
        assert base.exists(), f"no-FINAL path must promote the checkpoint to {base}"
        print("PASS no-FINAL run still delivers the banked best candidate (the lost-chair fix)")
    finally:
        _clean_besteffort_box()
        os.path.exists(ckpt) and os.remove(ckpt)


if __name__ == "__main__":
    test_salvage_sound_plan()
    test_noncoherent_not_salvaged()
    test_broken_plan_not_salvaged()
    test_fail_still_raises_but_salvages()
    test_promote_checkpoint_delivers()
    test_promote_broken_checkpoint_none()
    test_no_final_still_promotes_checkpoint()
    print("\nALL best-effort checkpoint tests passed.")
