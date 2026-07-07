---
name: primitive_planning
version: "1.0"
purpose: >
  Convert a parsed intent object into a structured PrimitivePlan JSON by
  selecting the best-matching primitive from the library and resolving all
  required parameters.
used_by:
  - planner (primitive-selection step of every plan)
inputs:
  - intent: "Output of intent_extraction skill"
  - primitive_schema: "Schema for the chosen catalog primitive"
  - dimension_reasoning_skill: "dimension_reasoning skill content"
outputs:
  - primitive: "Chosen primitive name string"
  - parameters: "Dict of param_name → resolved numeric value (mm)"
  - description: "One-sentence shape description"
tags: [planning, primitives, CSG, phase1]
token_budget: low   # ~400 tokens body — load always
---

# Skill: Primitive Planning

Convert a geometry intent into a structured **PrimitivePlan JSON** using the
primitive library. This is **Phase 1 / Steps 2–3** of the RLM pipeline.

## Primitive Selection Rules

- Match the physical description to the closest schema in `primitives/library.json`.
  (e.g., use `cone` for cones, `cylinder` for shafts, `box` for blocks)
- If a shape cannot map to a single primitive, use CSG: combine multiple
  primitives with `union` (add) and `cut` (subtract) operations.
- Every parameter in the schema **must** have a numeric value. Infer sensible
  engineering defaults if the prompt does not specify them.
- All units are **mm**. Never mix units.

## MANDATORY: Hollow / Flow-Through Parts

If the prompt describes (or implies) a part that fluid, air, cable, or another
part **passes through** — adapter, duct, pipe, tube, nozzle, manifold, funnel,
sleeve, coupling, bushing, transition, hose fitting, vent — the part **MUST be
hollow with an open passage**, not a solid block filling the same envelope.

This is easy to miss: a solid block shaped exactly like the part's outer
envelope renders identically to the correct hollow part from every EXTERIOR
view, and passes `is_watertight`/`open_holes==0` mesh checks cleanly (those
checks assert "no leaks," not "matches intent"). It is a real, silent defect —
verified case: a "rectangular-to-round duct transition adapter" (flange +
lofted transition + neck) was planned as three solid unioned primitives with
no hollow feature at all; it passed every check and looked correct from
outside, but was a solid plug with zero open passage.

**Fix — always include one of:**
- A `shell` FinishOp on the accumulated body (wall thickness, opens the
  end face(s) so fluid/air can pass) — the usual choice for a lofted/union body.
- A hollow primitive for the relevant sections (`tube`, `hollow_cylinder`)
  instead of their solid counterparts (`sweep`, `cylinder`).
- A through-cut: subtract a smaller matching solid (scaled-down profile/loft/
  tube) along the same axis/path as the outer envelope.

Before finalizing any adapter/duct/pipe/tube/nozzle/manifold/funnel plan, ask:
"does this have an open passage through it, or did I just build a solid shape
that LOOKS right from outside?" If in doubt, it needs a `shell` or through-cut.

## CSG Operation Keys

Each step in a plan must contain:

| Key | Description |
|---|---|
| `id` | Unique name/identifier for this primitive |
| `primitive` | Name from `library.json` |
| `operation` | `"base"` · `"union"` (add) · `"cut"` (subtract) |
| `parameters` | Key-value of numeric params matching the schema |
| `position` | `[x, y, z]` — center/origin placement in mm |
| `orientation` | `[rx, ry, rz]` — rotation in degrees |

## PrimitivePlan JSON Example (Cone on Cylindrical Flange)

```json
[
  {
    "id": "base_flange",
    "primitive": "cylinder",
    "operation": "base",
    "parameters": { "radius": 15.0, "height": 5.0 },
    "position": [0.0, 0.0, 0.0],
    "orientation": [0.0, 0.0, 0.0]
  },
  {
    "id": "cone_body",
    "primitive": "cone",
    "operation": "union",
    "parameters": { "base_diameter": 30.0, "top_diameter": 0.0, "height": 40.0 },
    "position": [0.0, 0.0, 5.0],
    "orientation": [0.0, 0.0, 0.0]
  }
]
```

> **Critical**: Position offsets must correctly stack primitives to avoid
> overlaps or gaps. Apply `dimension_reasoning` rules when computing `position`.

---

## FINISH STEP Schema

Finish steps act on the **whole accumulated body** (not a new primitive). Place them after all CSG steps.

```json
{ "id": "f1", "op": "<finish_op>", "selector": "<edge/face>", "value": <number|list>,
  "positions": [[x,y],...], "face": ">Z" }
```

| `op` | What it does | Required fields |
|---|---|---|
| `fillet` | Round edges | `selector`, `value` (radius mm) |
| `chamfer` | Bevel edges | `selector`, `value` (length mm) |
| `shell` | Hollow body (open one face) | `selector` (face to open), `value` (wall thickness mm) |
| `hole` | Drill simple holes at (x,y) points on a face | `face`, `value` (diameter mm), `positions` |
| `cbore` | Counterbored holes | `face`, `value` [clr_dia, bore_dia, bore_depth], `positions` |
| `csk` | Countersunk holes | `face`, `value` [clr_dia, csk_dia, csk_angle_deg], `positions` |
| `mirror` | Mirror body about a plane | `selector` ("XY"/"XZ"/"YZ") |

**CadQuery selector cheatsheet:**
- `">Z"` — top face (highest Z)
- `"<Z"` — bottom face
- `"|Z"` — all Z-parallel edges (verticals)
- `"%Circle"` — all circular edges
- `">Z[-2]"` — second-from-top face

Wrong selectors on fillet/chamfer now RAISE (OCCT StdFail) and route to the replanner — they are NOT silently skipped. Pick the correct selector.

---

## OPTIONAL: Section View (`section`)

Top-level plan key (sibling of `part_name` / `steps`), NOT a step. Tells the
renderer where to slice the part for the interior "section" view the verifier sees.

```json
{ "part_name": "...", "steps": [ ... ],
  "section": { "normal": [1, 0, 0], "point": [0, 0, 0] } }
```

- `normal` — cut-plane normal `[x, y, z]`.
- `point`  — a point the plane passes through (mm), usually the center of the feature.

**Emit `section` ONLY when the feature to inspect is OFF-CENTER** (eccentric bore,
internal boss on one side). For symmetric shells/cavities OMIT it — the renderer
auto-cuts through the center of mass along the shortest axis, which already
bisects a centered cavity.
