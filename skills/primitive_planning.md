---
name: primitive_planning
version: "2.0"
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

- **Consult the reference first.** It holds standard CSG recipes AND past designs
  a user confirmed correct (keyed by their original request). A matching approved
  design already resolves primitive choice, parameters, and step order — adapt it
  instead of re-deriving. Reuse proven work before inventing.
- Match the physical description to the closest schema in `primitives/library.json`.
  (e.g., use `cone` for cones, `cylinder` for shafts, `box` for blocks)
- If a shape cannot map to a single primitive, use CSG: combine multiple
  primitives with `union` (add) and `cut` (subtract) operations.
- Every parameter in the schema **must** have a numeric value. Infer sensible
  engineering defaults if the prompt does not specify them.
- All units are **mm**. Never mix units.

---

## ★ SMOOTH PROFILES — When and How

Every profile-based primitive (`profile_extrude`, `revolve`, `loft`, `loft_between`,
`sweep`, `taper_extrude`) has a `smooth` parameter (default `false`).

| `smooth: false` (default) | `smooth: true` |
|---|---|
| Connects control points with **straight line segments** → flat facets, angular silhouette | Fits a **smooth Catmull-Rom spline** through the control points → true curve |

**Set `smooth: true` when the shape has a curved silhouette** — NOT when the
cross-section is genuinely straight-edged (brackets, gear teeth, rectangular extrusions).

### Shapes That Require `smooth: true`

| Shape | Primitive | Why smooth? |
|---|---|---|
| Vase, bottle, cup (outer profile) | `revolve` | The silhouette curves; polyline gives a faceted lathe-turning look |
| Knob, ergonomic grip | `revolve` + `smooth: true` | Organic contour |
| Lens, dome, parabolic reflector | `revolve` + `smooth: true` | Continuously curved surface |
| Propeller / turbine blade cross-section | `loft` + `smooth: true` | Aerofoil profile |
| Car body panel cross-section | `profile_extrude` + `smooth: true` | Smooth stylistic curve |
| Wing rib | `loft_between` + `smooth_top` / `smooth_bottom` | Different radii at each end |
| Swept pipe around a curve | `sweep` + `smooth: true` | Circular section follows curved path |

### Worked Example — Smooth Vase Silhouette

```json
{
  "id": "body",
  "primitive": "revolve",
  "operation": "base",
  "parameters": {
    "profile": [
      [0.0,  0.0],
      [6.0,  0.0],
      [8.0,  8.0],
      [5.5, 16.0],
      [7.0, 24.0],
      [4.0, 32.0],
      [0.0, 32.0]
    ],
    "angle": 360.0,
    "smooth": true
  }
}
```

> The x-coordinates define the outer radius at each height level. With `smooth: true`
> the silhouette is a continuous curve through those control points — NOT a stack of
> truncated cones.

### Hollow Turned Parts (Vase, Cup, Glass, Bowl) — `revolve` + `shell`

For any hollow rotationally-symmetric part, the correct recipe is:

1. **`revolve`** the outer solid profile with `smooth: true`
2. **FinishStep `shell`** to hollow it (open the top face)

```json
{
  "steps": [
    {
      "id": "body",
      "primitive": "revolve",
      "operation": "base",
      "parameters": {
        "profile": [[0,0],[4,0],[5,12],[3.5,24],[0,24]],
        "angle": 360.0,
        "smooth": true
      }
    },
    { "id": "hollow", "op": "shell", "selector": ">Z", "value": 1.5 }
  ]
}
```

> **Do NOT** use `hollow_cylinder` for vases — it produces a straight-walled tube.
> `hollow_cylinder` is only correct for pipes and tubes with truly uniform cross-sections.

---

## CSG Operation Keys

Each step in a plan must contain:

| Key | Description |
|---|---|
| `id` | Unique name/identifier for this primitive |
| `primitive` | Name from `library.json` |
| `operation` | `"base"` · `"union"` (add) · `"cut"` (subtract) · `"intersect"` |
| `parameters` | Key-value of numeric params matching the schema |
| `position` | `[x, y, z]` — center/origin placement in mm |
| `orientation` | `[rx, ry, rz]` — rotation in degrees |

---

## FINISH STEP Schema

Finish steps act on the **whole accumulated body** (not a new primitive). Place them after all CSG steps.

```json
{ "id": "f1", "op": "<finish_op>", "selector": "<edge/face>", "value": <number|list>,
  "positions": [[x,y],...], "face": ">Z", "face_scope": "<face selector, fillet/chamfer only>" }
```

| `op` | What it does | Required fields |
|---|---|---|
| `fillet` | Round selected edges | `selector`, `value` (radius mm), optional `face_scope` |
| `chamfer` | Bevel selected edges | `selector`, `value` (length mm), optional `face_scope` |
| `shell` | Hollow body (open one face) | `selector` (face to open), `value` (wall thickness mm) |
| `hole` | Drill simple holes at (x,y) points on a face | `face`, `value` (diameter mm), `positions` |
| `cbore` | Counterbored holes | `face`, `value` [clr_dia, bore_dia, bore_depth], `positions` |
| `csk` | Countersunk holes | `face`, `value` [clr_dia, csk_dia, csk_angle_deg], `positions` |
| `mirror` | Mirror body about a plane & union w/ original | `selector` ("XY"/"XZ"/"YZ") |
| `face_feature` | Circular boss or hole on ANY one face — planar OR curved | `selector` (face, must match exactly one), `value` [diameter, depth] |

### `face_scope` — fillet/chamfer only ONE step's rim
A plain `fillet`/`chamfer` selector (e.g. `"|Z"`, `"%Circle"`) matches edges
across the **whole body**. On a multi-level stacked part, that rounds every
matching edge everywhere — if you only want ONE level's rim rounded, add
`"face_scope": "<face selector>"`: it restricts the op to that face's own
edges first, THEN applies `selector` within them (leave `selector` empty for
"all of that face's edges").
```json
{ "id": "f", "op": "fillet", "face_scope": ">Z", "value": 2.0 }
```
→ rounds only the topmost step's rim; every other edge in the part is untouched.

### `face_feature` — a boss or hole on an angled or CURVED face
For a stud/boss/vent on a slanted or curved surface (housing wall, cylindrical
tank side, dome) — not just the flat top/bottom a normal `position`+`orientation`
step can reach. Centered on the selected face automatically (no `position` math
needed — the compiler samples the real surface normal at that face's center,
so it works even where the surface curves and a single "orientation" angle
couldn't). `value = [diameter, depth]`: **positive depth = boss** (added
outward), **negative depth = hole** (bored inward).
```json
{ "id": "boss", "op": "face_feature", "selector": "%Cylinder", "value": [8.0, 6.0] }
```
→ an 8mm-diameter, 6mm-tall round boss on the cylindrical side wall.
```json
{ "id": "vent", "op": "face_feature", "selector": "%Cylinder", "value": [5.0, -12.0] }
```
→ a 5mm hole bored 12mm into that same curved wall.

> The `selector` must resolve to exactly ONE face — pick a selector specific
> enough to be unambiguous (`"%Cylinder"` on a part with only one curved face,
> `">X"` only if just one face is X-most). A selector matching several faces
> silently uses just the first one.

---

## ★ FULL SELECTOR CHEATSHEET

Selectors are string arguments to `edges(...)`, `faces(...)`, `vertices(...)` in FinishSteps.

### Direction / Position Selectors
| Selector | Meaning | Typical use |
|---|---|---|
| `">Z"` | Topmost face (highest Z centroid) | `shell` open top, `hole` on top face |
| `"<Z"` | Bottom face (lowest Z centroid) | Chamfer the base edge ring |
| `">X"`, `"<X"`, `">Y"`, `"<Y"` | Face/edge farthest / nearest in that axis | Side face operations |
| `">Z[-2]"` | 2nd face from top | Feature on a step below the top |
| `"<Z[-2]"` | 2nd from bottom | Feature on a step above the base |

### Parallel / Perpendicular Selectors
| Selector | Meaning | Typical use |
|---|---|---|
| `"\|Z"` | All edges **parallel** to Z (vertical edges) | Fillet vertical corners of a box |
| `"\|X"` | All edges parallel to X | Fillet horizontal long edges |
| `"#Z"` | All edges **perpendicular** to Z (horizontal rim edges) | Fillet/chamfer top and bottom rims |
| `"#X"` | Edges perpendicular to X | Cross-direction rims |

### Geometry Type Selectors
| Selector | Meaning | Typical use |
|---|---|---|
| `"%Circle"` | All **circular** edges | Fillet/chamfer cylinder rims and hole lips |
| `"%Line"` | All **straight** edges only | Chamfer only flat edges, skip curves |
| `"%Plane"` | All **planar** faces | Shell only flat faces, skip curved |
| `"%Cylinder"` | All cylindrical faces | Select tube walls |

### Combined Selectors (logical)
```
">Z or <Z"      →  both top and bottom faces  (shell to open both ends of a tube)
">Z and %Plane" →  only flat top face (not a curved dome top)
```

> **Critical:** Wrong selectors on fillet/chamfer now **RAISE** (OCCT StdFail) and route to
> the replanner — they are NOT silently skipped. Choose the correct selector.

### Most Common Patterns
```
Fillet all vertical edges of a box:        selector: "|Z"
Chamfer all circular edges (cylinder rim): selector: "%Circle"
Chamfer horizontal top/bottom rims:        selector: "#Z"
Shell open the top:                        selector: ">Z"   (shell op)
Shell open both top and bottom:            selector: ">Z or <Z"
Hole on top face:                          face: ">Z"
Hole on bottom face:                       face: "<Z"
```

---

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
