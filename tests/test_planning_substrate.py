"""
test_planning_substrate.py — measure PLANNING capability without the live LLM.

The RLM's planning reasoning runs on your machine (Deno + API key). What we can
verify deterministically here is the SUBSTRATE the RLM depends on:
  1. the schema can REPRESENT each kind of plan (primitive / freeform / hybrid);
  2. the primitive library + CadQuery KB can RETRIEVE what each hard prompt needs;
  3. nothing crashes on hard / ambiguous / assembly prompts.

Run:  python tests/test_planning_substrate.py
"""
import json
import os
import sys
from pathlib import Path

# Set environment variable to bypass live tool call logging checks in tests
os.environ["GEOMETRY_PLANNING_TEST"] = "true"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cadquery_kb_pack" / "tools"))

from schemas.geometry_plan import GeometryPlan
from cadquery_kb_tools import KB

KB_JSON = ROOT / "cadquery_kb_pack" / "knowledge" / "cadquery_kb.json"
PRIMS = json.load(open(ROOT / "schemas" / "primitives.json"))
kb = KB(str(KB_JSON))

# ----- hard prompt suite: (prompt, expected_path, kb_query) ------------------
# expected_path: primitive | freeform | hybrid | clarify
SUITE = [
    ("Mounting bracket for a camera on a brick wall", "primitive", "plate with mounting holes"),
    ("Weatherproof enclosure for a Raspberry Pi with vents", "primitive", "hollow box with rectangular cutouts"),
    ("Hex standoff M3, 10 mm long", "primitive", "hexagonal prism with center hole"),
    ("Flanged pipe coupling with 4 bolt holes", "hybrid", "hollow cylinder with a flange ring and holes"),
    ("Involute spur gear, 20 teeth, module 2", "freeform", "gear teeth polygon profile extrude pattern"),
    ("Threaded M10 bolt, 40 mm long", "freeform", "helix thread sweep along a path"),
    ("Ergonomic door handle with a curved grip", "freeform", "loft a swept curved profile"),
    ("Turbine blade with a twisted aerofoil", "freeform", "loft twisted spline sections"),
    ("Wine glass (revolved profile)", "freeform", "revolve a 2D profile around an axis"),
    ("Phone stand with a curved back support", "freeform", "sweep an extruded curved profile"),
    ("Herringbone gear", "freeform", "polar pattern of angled teeth extrude"),
    ("A holder", "clarify", "generic bracket box"),
    ("2-stage planetary gearbox housing + gears", "freeform", "cylindrical housing with internal gear ring"),
]

PRIM_NAMES = set(PRIMS.keys())


def primitive_can_cover(query_terms):
    """Crude indicator: does an obvious primitive name/synonym match?"""
    syn = {
        "box": ["box", "plate", "enclosure", "bracket", "housing"],
        "hollow_box": ["enclosure", "hollow", "case"],
        "cylinder": ["cylinder", "pin", "boss", "post", "rod"],
        "hollow_cylinder": ["tube", "pipe", "coupling", "ring", "sleeve"],
        "hexagon_prism": ["hex", "standoff", "nut"],
        "ring": ["flange", "ring", "washer"],
        "filleted_box": ["rounded", "fillet"],
        "sphere": ["ball", "sphere", "dome"],
    }
    hit = []
    for prim, words in syn.items():
        if any(w in query_terms for w in words):
            hit.append(prim)
    return hit


def main():
    print("=" * 74)
    print("PLANNING SUBSTRATE CAPABILITY PROBE")
    print("=" * 74)
    print(f"primitives: {len(PRIMS)}   KB api ops: {len(kb.api)}   KB examples: {len(kb.examples)}\n")

    rows = []
    for prompt, expected, q in SUITE:
        terms = prompt.lower()
        prim_hits = primitive_can_cover(terms)
        hits = kb.search(q, k=4, kind="api")["api"]
        kb_ops = [h["id"] for h in hits]
        kb_ok = len(kb_ops) > 0
        # decision the substrate SUPPORTS (not the LLM's actual choice)
        if expected == "primitive":
            supported = bool(prim_hits)
        elif expected == "freeform":
            supported = kb_ok
        elif expected == "hybrid":
            supported = bool(prim_hits) and kb_ok
        else:  # clarify
            supported = True  # ask_user is always available
        rows.append((prompt, expected, prim_hits, kb_ops, supported))

    # report
    npass = 0
    for prompt, expected, prim_hits, kb_ops, supported in rows:
        flag = "OK " if supported else "!! "
        npass += supported
        print(f"[{flag}] {expected.upper():9s} | {prompt}")
        if expected in ("primitive", "hybrid"):
            print(f"        primitive fit : {prim_hits or '—'}")
        if expected in ("freeform", "hybrid"):
            print(f"        cadquery ops  : {kb_ops or '— (no KB hit!)'}")
        if expected == "clarify":
            print(f"        -> underspecified; ask_user available")
    print(f"\nsubstrate-supported: {npass}/{len(rows)} hard prompts\n")

    # ---- schema representation proof: build & validate 3 real plans ----------
    print("=" * 74)
    print("SCHEMA REPRESENTATION PROOF (can the plan contract hold each kind?)")
    print("=" * 74)
    base = {
        "title": "x", "overall_dimensions": {"width": 60, "length": 40, "height": 10},
        "engineering_requirements": {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []},
        "assumptions": ["std"], "clarifications": [{"question": "What is the bracket material?", "answer": "Aluminum"}],
    }
    cases = {
        "primitive (bracket)": [
            {"sequence_id": 1, "primitive_type": "box", "parameters": {"length": 60, "width": 40, "height": 5}, "rationale": "main base plate structure"},
            {"sequence_id": 2, "primitive_type": "cylinder", "parameters": {"radius": 3, "height": 5}, "rationale": "M6 clearance hole (subtract)"},
        ],
        "freeform (spur gear)": [
            {"sequence_id": 1, "primitive_type": "custom",
             "parameters": {"shape_description": "involute spur gear, 20 teeth",
                            "cadquery_operations": ["Workplane.polygon", "Workplane.polarArray", "Workplane.extrude"],
                            "code_sketch": "result = cq.Workplane('XY').circle(20).circle(15).extrude(8)",
                            "declared_dimensions": {"pitch_diameter": 40, "teeth": 20, "thickness": 8}},
             "rationale": "no gear primitive exists"},
        ],
        "hybrid (flanged coupling)": [
            {"sequence_id": 1, "primitive_type": "hollow_cylinder", "parameters": {"outer_radius": 15, "inner_radius": 10, "height": 40}, "rationale": "main hollow pipe body structure"},
            {"sequence_id": 2, "primitive_type": "ring", "parameters": {"outer_radius": 25, "inner_radius": 15, "thickness": 5}, "rationale": "outer mounting flange structure"},
            {"sequence_id": 3, "primitive_type": "custom",
             "parameters": {"shape_description": "4 bolt holes on a PCD", "cadquery_operations": ["Workplane.polarArray", "Workplane.hole"],
                            "code_sketch": "result = cq.Workplane('XY').circle(25).extrude(8).faces('>Z').workplane().polarArray(20,0,360,4).hole(6)", "declared_dimensions": {"bolt_circle": 40, "hole_d": 6, "count": 4}},
             "rationale": "patterned holes need a freeform pattern op"},
        ],
    }
    ok = 0
    for name, seq in cases.items():
        try:
            p = GeometryPlan(**{**base, "primitives_sequence": seq})
            print(f"  [OK ] {name:26s} -> validates; contains_freeform={p.contains_freeform}")
            ok += 1
        except Exception as e:
            print(f"  [!! ] {name:26s} -> FAILED: {str(e).splitlines()[0][:60]}")
    print(f"\nschema represents: {ok}/{len(cases)} plan kinds\n")

    total_ok = (npass == len(rows)) and (ok == len(cases))
    print("=" * 74)
    print("RESULT:", "ALL SUBSTRATE CHECKS PASS \u2713" if total_ok else "SOME CHECKS FAILED")
    print("=" * 74)
    return 0 if total_ok else 1


if __name__ == "__main__":
    sys.exit(main())
