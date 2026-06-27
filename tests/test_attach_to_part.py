"""
attach.to a PART GROUP name (deterministic). In an assembly the agent reasons in PARTS, but a part
can be several steps (e.g. backrest = outer frame + spine). `attach.to` now resolves a part-group
name (anchoring against the combined bbox of the part's member steps), so the agent can mate to
"the backrest" without knowing a sub-step name — the friction that errored a real run
("unknown target 'backrest'"). A genuinely unknown target still errors clearly.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))
os.environ.setdefault("PRIMITIVES_JSON_DATA", (ROOT / "schemas" / "primitives.json").read_text())

import kernel                      # noqa: E402
import verify as verify_mod        # noqa: E402


def _reqs():
    return {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []}


def test_attach_to_part_group_resolves_to_one_object():
    plan = {"title": "Attach To Part", "assembly_kind": "assembly",
            "overall_dimensions": {"width": 100, "length": 100, "height": 300},
            "engineering_requirements": _reqs(), "assumptions": [], "clarifications": [],
            "primitives_sequence": [
                {"sequence_id": 1, "name": "seat", "part": "seat", "primitive_type": "box",
                 "parameters": {"length": 60, "width": 60, "height": 10}, "operation": "new",
                 "position": [0, 0, 0], "rationale": "the seat base the backrest attaches onto"},
                {"sequence_id": 2, "name": "backrest_outer", "part": "backrest", "primitive_type": "box",
                 "parameters": {"length": 60, "width": 8, "height": 80}, "operation": "new",
                 "attach": {"to": "seat", "at": "back", "my_anchor": "front"},
                 "rationale": "outer frame of the multi-step backrest part"},
                {"sequence_id": 3, "name": "backrest_spine", "part": "backrest", "primitive_type": "box",
                 "parameters": {"length": 8, "width": 8, "height": 80}, "operation": "join",
                 "attach": {"to": "backrest_outer", "at": "center", "my_anchor": "center"},
                 "rationale": "central spine fused into the backrest part"},
                {"sequence_id": 4, "name": "headrest", "part": "headrest", "primitive_type": "box",
                 "parameters": {"length": 50, "width": 8, "height": 20}, "operation": "new",
                 "attach": {"to": "backrest", "at": "top", "my_anchor": "bottom"},
                 "rationale": "headrest mated to the backrest PART group (not a step)"}]}
    res = kernel.build_plan(plan)
    assert res["ok"], res
    rep = verify_mod.verify_solid(res["solid"], plan=plan, part_solids=res["meta"]["part_solids"])
    assert rep["verdict"] == "PASS", f"attach-to-part must yield a coherent object: {rep.get('localized_fix')}"
    assert rep["coherence"]["num_clusters"] == 1, rep["coherence"]
    print("PASS attach.to a PART group name resolves to ONE coherent object")


def test_unknown_target_still_errors():
    plan = {"title": "Bad Attach", "assembly_kind": "assembly",
            "overall_dimensions": {"width": 100, "length": 100, "height": 100},
            "engineering_requirements": _reqs(), "assumptions": [], "clarifications": [],
            "primitives_sequence": [
                {"sequence_id": 1, "name": "a", "part": "a", "primitive_type": "box",
                 "parameters": {"length": 40, "width": 40, "height": 40}, "operation": "new",
                 "position": [0, 0, 0], "rationale": "base box for the unknown-target test"},
                {"sequence_id": 2, "name": "b", "part": "b", "primitive_type": "box",
                 "parameters": {"length": 40, "width": 40, "height": 40}, "operation": "new",
                 "attach": {"to": "nope", "at": "top", "my_anchor": "bottom"},
                 "rationale": "attaches to a genuinely nonexistent target"}]}
    res = kernel.build_plan(plan)
    assert not res["ok"], "an unknown attach target must fail the build"
    assert "unknown target" in (res.get("error") or ""), res.get("error")
    print("PASS a genuinely unknown attach target still errors clearly")


if __name__ == "__main__":
    test_attach_to_part_group_resolves_to_one_object()
    test_unknown_target_still_errors()
    print("\nALL attach-to-part tests passed.")
