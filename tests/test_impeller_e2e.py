"""
Phase 9 (end-to-end): a full centrifugal impeller as ONE monolithic single_solid, through the REAL
server path (schema validate -> kernel build -> fixed battery -> token mint), entirely offline.

This is the object the impeller run could not produce (it delivered a single floating blade because
the hub was silently dropped on every join). With the monolithic-fusion fixes it must now build as
ONE sound, connected body and earn a real verification_token:

  hub   = revolved_profile   (turned cone-ish backplate, Ø100 -> Ø30, 50mm)
  bore  = cylinder (cut)      (central shaft hole)
  blades= twisted_loft + pattern{radial, count 7} + operation join   (7 vanes fused to the hub)

It also proves the SCHEMA accepts `twisted_loft` (the impl runs _validate_plan_schema first) and the
pattern+join fusion path is FINAL-able (token minted, deliverable).
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
os.environ["FORGECAD_CHECKPOINT_FILE"] = tempfile.mktemp(suffix=".impeller_ckpt.json")
os.environ["FORGECAD_RUN_SECRET"] = "impeller_e2e_secret"
os.environ["RLM_MODEL_API_KEY"] = "dummy"

import geometry_server as gs       # noqa: E402


def _reqs():
    return {"functional": ["aerodynamic flow path", "central bore for shaft"],
            "environmental_thermal": ["high rpm / temperature"],
            "structural": ["centrifugal strength"], "manufacturing_cost": ["machinable"]}


def _impeller_plan(count=7):
    blade = {"sequence_id": 3, "name": "blade", "primitive_type": "twisted_loft",
             "parameters": {
                 "profile": [[-17.0, -1.5], [17.0, -1.5], [17.0, 1.5], [-17.0, 1.5]],
                 "stations": [[0.0, 29.0, 0.0, 1.0], [12.5, 29.0, 6.0, 1.0],
                              [25.0, 29.0, 12.0, 1.0], [37.5, 29.0, 18.0, 0.95],
                              [50.0, 29.0, 24.0, 0.85]]},
             "operation": "join",
             "pattern": {"kind": "radial", "count": count, "axis": "z"},
             "rationale": "one twisted vane, patterned around the hub and fused"}
    return {"title": "Centrifugal Impeller", "assembly_kind": "single_solid",
            "overall_dimensions": {"width": 100, "length": 100, "height": 50},
            "engineering_requirements": _reqs(), "assumptions": [],
            "clarifications": [{"question": "outer diameter?", "answer": "100 mm"},
                               {"question": "blade count?", "answer": "7"}],
            "primitives_sequence": [
                {"sequence_id": 1, "name": "hub", "primitive_type": "revolved_profile",
                 "parameters": {"profile": [[50, 0], [48, 5], [42, 15], [32, 30], [20, 45], [15, 50]],
                                "end_fillet": 0.0},
                 "operation": "new", "rationale": "central hub / backplate"},
                {"sequence_id": 2, "name": "bore", "primitive_type": "cylinder",
                 "parameters": {"radius": 10, "height": 60}, "operation": "cut",
                 "position": [0, 0, 25], "rationale": "central shaft bore"},
                blade],
            "contains_freeform": False}


def test_full_impeller_builds_one_sound_solid_with_token():
    # Stub the vision critic so the run is fully offline + deterministic (token mints on geometry
    # PASS regardless of fidelity; we stub only to avoid a live vision call).
    os.environ[gs.fidelity_mod.STUB_ENV] = json.dumps(
        {"recognizable": True, "status": "pass", "missing_major_features": []})
    try:
        out = gs._build_verify_render_impl(_impeller_plan(count=7))
    finally:
        os.environ.pop(gs.fidelity_mod.STUB_ENV, None)

    assert out.get("stage") != "validate", f"schema must accept twisted_loft + pattern: {out.get('errors')}"
    assert out.get("stage") != "build", f"impeller must build (no body drop): {out.get('error')}"
    assert out["verdict"] == "PASS", f"impeller must verify PASS: {out.get('report', {}).get('localized_fix')}"
    assert out.get("verification_token"), "a PASS impeller must mint a verification_token (FINAL-able)"

    checks = {c["name"]: c for c in out["report"]["checks"]}
    assert checks["component_count"]["passed"], checks["component_count"]["detail"]
    assert checks["no_self_intersections"]["passed"], checks["no_self_intersections"]["detail"]
    assert checks["watertight"]["passed"], checks["watertight"]["detail"]
    ndb = checks.get("no_dropped_body")
    assert ndb is not None and ndb["passed"], f"no body may be dropped: {ndb}"

    bb = out["measured_bbox"]            # [x, y, z]
    assert 80 <= max(bb[0], bb[1]) <= 110, f"impeller footprint ~Ø100 expected, got {bb}"
    assert 46 <= bb[2] <= 56, f"impeller height ~50 expected, got {bb}"
    print(f"PASS full impeller: ONE sound body, token minted, bbox={[round(x,1) for x in bb]}")

    # Clean up the render PNG + the temp checkpoint this test produced (leave the tree tidy).
    for p in (out.get("png_path"), os.environ.get("FORGECAD_CHECKPOINT_FILE")):
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


if __name__ == "__main__":
    test_full_impeller_builds_one_sound_solid_with_token()
    print("\nimpeller end-to-end test passed.")
