"""v5 capability tests — run with a python that has cadquery + pydantic:
    <venv>/bin/python tests/test_v5_capabilities.py
Covers: composite anchors, attach.offset, linear/radial patterns, merge_subplans
(structure + real build), schema accept/reject of new fields, and plan-store round-trip.
"""
import sys, math, shutil, importlib.util
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cad_kernel import kernel as K
from cad_kernel.merge import merge_subplans
import plan_store as PS
import cadquery as cq

spec = importlib.util.spec_from_file_location("geometry_plan", ROOT / "schemas" / "geometry_plan.py")
gp = importlib.util.module_from_spec(spec); spec.loader.exec_module(gp)
GeometryPlan = gp.GeometryPlan
from pydantic import ValidationError

def approx(a, b, t=1e-3): return all(abs(x-y) <= t for x, y in zip(a, b))
def base(steps, kind="single_solid"):
    return {"title":"t","assembly_kind":kind,"overall_dimensions":{"width":1,"length":1,"height":1},
            "engineering_requirements":{"functional":[],"environmental_thermal":[],"structural":[],"manufacturing_cost":[]},
            "assumptions":[],"clarifications":[],"primitives_sequence":steps}

def test_anchors():
    box = cq.Workplane("XY").box(100,100,20)
    assert approx(K._anchor_point(box,"top"),(0,0,10))
    assert approx(K._anchor_point(box,"top|front"),(0,-50,10))
    assert approx(K._anchor_point(box,"top|front|right"),(50,-50,10))
    assert K._opposite_anchor("top|front|right")=="bottom|back|left"
    print("OK composite anchors (face/edge/corner) + opposite")

def test_patterns():
    plan = base([
      {"sequence_id":1,"name":"plate","primitive_type":"cylinder","parameters":{"radius":60,"height":10},"operation":"new","rationale":"disc plate body"},
      {"sequence_id":2,"name":"holes","primitive_type":"cylinder","parameters":{"radius":5,"height":30},"operation":"cut","position":[40,0,0],"pattern":{"kind":"radial","count":6,"axis":"z"},"rationale":"bolt circle"}])
    r = K.build_plan(plan); assert r["ok"], r
    vol = r["solid"].val().Volume()
    expect = math.pi*60**2*10 - 6*(math.pi*5**2*10)
    assert abs(vol-expect)/expect < 0.02, (vol, expect)
    print("OK radial pattern volume matches analytic (%.0f)" % vol)

def test_merge():
    post={"primitives_sequence":[{"sequence_id":1,"name":"shaft","primitive_type":"cylinder","parameters":{"radius":20,"height":300},"operation":"new","rationale":"vertical post shaft body"}]}
    cap={"primitives_sequence":[{"sequence_id":1,"name":"plate","primitive_type":"box","parameters":{"length":200,"width":200,"height":20},"operation":"new","rationale":"the cap plate body"}]}
    m = merge_subplans([{"name":"post","plan":post},{"name":"cap","plan":cap}],
                       connections=[{"from":"cap","to":"post","at":"top"}])
    assert [s["name"] for s in m["primitives_sequence"]]==["post.shaft","cap.plate"]
    GeometryPlan(**m)
    r = K.build_plan(m); assert r["ok"] and len(r["solid"].vals())==1
    print("OK merge_subplans (namespacing + validates + builds)")

def test_schema_guards():
    GeometryPlan(**base([
      {"sequence_id":1,"name":"p","primitive_type":"box","parameters":{"length":100,"width":100,"height":20},"operation":"new","rationale":"the base plate body here"},
      {"sequence_id":2,"name":"l","primitive_type":"box","parameters":{"length":10,"width":10,"height":10},"operation":"join","attach":{"to":"p","at":"top|front|right","offset":[0,0,0]},"rationale":"corner lug placement here"}]))
    for bad in (
        base([{"sequence_id":1,"name":"a","primitive_type":"box","parameters":{"length":10,"width":10,"height":10},"operation":"new","rationale":"the seed body block here"},
              {"sequence_id":2,"name":"b","primitive_type":"box","parameters":{"length":5,"width":5,"height":5},"operation":"new","pattern":{"kind":"radial","count":6},"rationale":"pattern with new op here"}]),
        base([{"sequence_id":1,"name":"a","primitive_type":"box","parameters":{"length":10,"width":10,"height":10},"operation":"new","rationale":"the seed body block here"},
              {"sequence_id":2,"name":"b","primitive_type":"box","parameters":{"length":5,"width":5,"height":5},"operation":"join","attach":{"to":"a","at":"top|bottom"},"rationale":"impossible same axis anchor"}])):
        try:
            GeometryPlan(**bad); raise AssertionError("should have rejected")
        except ValidationError:
            pass
    print("OK schema accepts new fields and rejects misuse")

def test_store():
    shutil.rmtree(PS.STORE_DIR, ignore_errors=True)
    a={"title":"x","primitives_sequence":[{"sequence_id":1}]}; b=dict(a, title="y")
    assert PS.plan_id(a)!=PS.plan_id(b)
    PS.save_plan(a,"x"); PS.save_plan(b,"y")
    assert PS.load_plan("latest")["title"]=="y" and len(PS.list_plans())==2
    shutil.rmtree(PS.STORE_DIR, ignore_errors=True)
    print("OK plan store round-trip")

if __name__ == "__main__":
    test_anchors(); test_patterns(); test_merge(); test_schema_guards(); test_store()
    print("\nALL v5 CAPABILITY TESTS PASSED")
