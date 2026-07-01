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

Wrong selectors silently no-op on fillet/chamfer (they're skipped, not errors). Pick the obvious one.
