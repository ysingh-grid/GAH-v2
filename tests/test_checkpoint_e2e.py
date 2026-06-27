"""
Fix B (deterministic, end-to-end): the agent-independent delivery guarantee.

The live run produced a geom-PASS chair but the agent couldn't FINAL it (mcp_call string read-path)
AND no best-effort artifact appeared — so a passing chair yielded nothing. This test locks down the
FULL host chain that must make delivery agent-independent: a geom-PASS through
build_verify_render BANKS a checkpoint, and the orchestrator PROMOTES it to a real export — with NO
dependency on the agent parsing anything or calling FINAL.

Import order matters: FORGECAD_CHECKPOINT_FILE must be set BEFORE importing geometry_server (it
reads the path at import; the call-time re-read is also covered).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))
os.environ["PRIMITIVES_JSON_DATA"] = (ROOT / "schemas" / "primitives.json").read_text()

CKPT = tempfile.mktemp(suffix=".forgecad_ckpt.json")
os.environ["FORGECAD_CHECKPOINT_FILE"] = CKPT
os.environ["FORGECAD_RUN_SECRET"] = "e2e_secret"
os.environ["RLM_MODEL_API_KEY"] = "dummy"

import geometry_server as gs       # noqa: E402  (reads _CHECKPOINT_FILE at import)
import orchestrator as orch        # noqa: E402


def _reqs():
    return {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []}


def _pass_assembly():
    return {"title": "E2E Chair", "assembly_kind": "assembly",
            "overall_dimensions": {"width": 80, "length": 40, "height": 40},
            "engineering_requirements": _reqs(), "assumptions": [], "clarifications": [],
            "primitives_sequence": [
                {"sequence_id": 1, "name": "a", "part": "a", "primitive_type": "box",
                 "parameters": {"length": 40, "width": 40, "height": 40}, "operation": "new",
                 "position": [0, 0, 0], "rationale": "base part a for the e2e checkpoint test"},
                {"sequence_id": 2, "name": "b", "part": "b", "primitive_type": "box",
                 "parameters": {"length": 40, "width": 40, "height": 40}, "operation": "new",
                 "attach": {"to": "a", "at": "right"}, "rationale": "part b attached to a"}]}


def _cleanup(outs):
    for o in (outs or []):
        try:
            os.path.exists(o) and os.remove(o)
        except Exception:
            pass
    for ext in ("exports/besteffort_E2E_Chair.stl", "exports/besteffort_E2E_Chair.step",
                "renders/besteffort_E2E_Chair.png"):
        p = ROOT / ext
        try:
            p.exists() and p.unlink()
        except Exception:
            pass
    try:
        os.path.exists(CKPT) and os.remove(CKPT)
    except Exception:
        pass
    import shutil
    try:
        (ROOT / "sessions").exists() and shutil.rmtree(ROOT / "sessions")
    except Exception:
        pass


def test_interpenetrating_sound_assembly_banks_last_resort_no_token():
    # A sound + coherent assembly that fails ONLY the mating gate (parts buried in each other) must:
    # (a) verdict FAIL, (b) mint NO token, (c) still bank a LAST-RESORT checkpoint (rank 0.5,
    # needs_review) so the orchestrator can deliver something — never nothing.
    import tempfile as _tf
    fresh = _tf.mktemp(suffix=".lastresort_ckpt.json")
    saved_file, saved_best = gs._CHECKPOINT_FILE, gs._BEST
    gs._CHECKPOINT_FILE = fresh
    os.environ["FORGECAD_CHECKPOINT_FILE"] = fresh
    gs._BEST = {"rank": -1}
    plan = {"title": "Interp Asm", "assembly_kind": "assembly",
            "overall_dimensions": {"width": 60, "length": 40, "height": 40},
            "engineering_requirements": _reqs(), "assumptions": [], "clarifications": [],
            "primitives_sequence": [
                {"sequence_id": 1, "name": "a", "part": "a", "primitive_type": "box",
                 "parameters": {"length": 40, "width": 40, "height": 40}, "operation": "new",
                 "position": [0, 0, 0], "rationale": "base box a for the interpenetration banking test"},
                {"sequence_id": 2, "name": "b", "part": "b", "primitive_type": "box",
                 "parameters": {"length": 40, "width": 40, "height": 40}, "operation": "new",
                 "position": [20, 0, 0], "rationale": "box b buried 50% into a (absolute position, not snapped)"}]}
    try:
        out = gs._build_verify_render_impl(plan)
        assert out["verdict"] == "FAIL", out
        assert not out.get("verification_token"), "an interpenetrating plan must NOT mint a token"
        assert "MATING GATE FAILED" in out.get("next_action", ""), out.get("next_action")
        assert os.path.exists(fresh), "sound+coherent-but-interpenetrating MUST bank a last-resort checkpoint"
        rec = json.loads(Path(fresh).read_text())
        assert rec.get("rank") == 0.5, rec
        assert rec.get("trust_tier") == "needs_review", rec
        print("PASS interpenetrating-but-sound: verdict FAIL, NO token, banked at last-resort rank 0.5")
    finally:
        gs._CHECKPOINT_FILE, gs._BEST = saved_file, saved_best
        os.environ["FORGECAD_CHECKPOINT_FILE"] = CKPT
        try:
            os.path.exists(fresh) and os.remove(fresh)
        except Exception:
            pass


def test_geom_pass_banks_checkpoint():
    # fidelity rejected (blocky) -> still a geom PASS + token, and it MUST bank a checkpoint.
    os.environ[gs.fidelity_mod.STUB_ENV] = json.dumps(
        {"recognizable": False, "missing_major_features": ["blocky"]})
    try:
        out = gs._build_verify_render_impl(_pass_assembly())
    finally:
        os.environ.pop(gs.fidelity_mod.STUB_ENV, None)
    try:
        assert out["verdict"] == "PASS", out
        assert out.get("verification_token"), "geom PASS must mint a token even with blocky fidelity"
        assert os.path.exists(CKPT), "geom PASS MUST bank a checkpoint file (agent-independent delivery)"
        rec = json.loads(Path(CKPT).read_text())
        assert rec.get("plan", {}).get("title") == "E2E Chair", rec
        print("PASS geom-PASS banks a checkpoint (rank=%s, trust=%s)" % (rec.get("rank"), rec.get("trust_tier")))
    finally:
        pass  # leave CKPT for the next test


def test_orchestrator_promotes_banked_checkpoint():
    # the checkpoint banked above must be promoted to a real best-effort export, agent-independent.
    assert os.path.exists(CKPT), "precondition: checkpoint must exist from the previous test"
    outs = orch._promote_best_candidate(CKPT)
    try:
        assert outs, "the orchestrator MUST deliver the banked geom-PASS (never nothing when a PASS existed)"
        assert all(os.path.exists(o) for o in outs), outs
        assert any("besteffort_E2E_Chair" in str(o) for o in outs), outs
        print("PASS orchestrator promotes the banked checkpoint to a real artifact (delivery is agent-independent)")
    finally:
        _cleanup(outs)


def test_delivery_survives_fast_rlm_raise():
    # C4: the engine RAISES when the agent exhausts its budget without FINAL. run_pipeline must still
    # promote the banked checkpoint. We monkeypatch fast_rlm.run to (1) bank a sound plan to the
    # checkpoint path the orchestrator passed it, then (2) raise like the engine does on no-FINAL.
    import json as _json

    sound = {"title": "C4 Delivery Box", "assembly_kind": "single_solid",
             "overall_dimensions": {"width": 30, "length": 30, "height": 30},
             "engineering_requirements": _reqs(), "assumptions": [], "clarifications": [],
             "primitives_sequence": [
                 {"sequence_id": 1, "name": "b", "primitive_type": "box",
                  "parameters": {"length": 30, "width": 30, "height": 30}, "operation": "new",
                  "rationale": "a sound box banked before the engine raised"}]}

    def fake_run(**kwargs):
        ck = kwargs["mcp_servers"]["geometry_kernel"]["env"]["FORGECAD_CHECKPOINT_FILE"]
        with open(ck, "w", encoding="utf-8") as f:
            _json.dump({"rank": 1, "trust_tier": "needs_review", "plan": sound,
                        "measured_bbox": [30, 30, 30], "fidelity": None}, f)
        raise RuntimeError("fast-rlm subagent failed: Did not finish the function stack before subagent died")

    orig = orch.fast_rlm.run
    orch.fast_rlm.run = fake_run
    raised = False
    try:
        orch.run_pipeline("design a box", [], None)
    except orch.PipelineError:
        raised = True
    except Exception as e:  # pragma: no cover
        raise AssertionError(f"expected PipelineError, got {type(e).__name__}: {e}")
    finally:
        orch.fast_rlm.run = orig
    base = ROOT / "exports" / "besteffort_C4_Delivery_Box.stl"
    try:
        assert raised, "run_pipeline must raise PipelineError after a no-FINAL engine raise"
        assert base.exists(), "the banked checkpoint MUST be delivered even though fast_rlm.run raised"
        print("PASS delivery survives a no-FINAL engine raise (checkpoint promoted) — the C4 guarantee")
    finally:
        for ext in ("exports/besteffort_C4_Delivery_Box.stl", "exports/besteffort_C4_Delivery_Box.step",
                    "renders/besteffort_C4_Delivery_Box.png"):
            p = ROOT / ext
            try:
                p.exists() and p.unlink()
            except Exception:
                pass
        import shutil
        try:
            (ROOT / "sessions").exists() and shutil.rmtree(ROOT / "sessions")
        except Exception:
            pass


if __name__ == "__main__":
    test_interpenetrating_sound_assembly_banks_last_resort_no_token()
    test_geom_pass_banks_checkpoint()
    test_orchestrator_promotes_banked_checkpoint()
    test_delivery_survives_fast_rlm_raise()
    print("\nALL checkpoint end-to-end tests passed.")
