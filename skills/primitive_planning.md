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

## Primitive Selection Principle (READ FIRST)

**Pick the SINGLE richest primitive that directly expresses the shape.** The
library has 22 primitives, not just `box` + `cylinder` — many build a feature
*intrinsically* in ONE robust step. Prefer an intrinsic construction primitive
over building a crude solid and then patching it with a FRAGILE post-hoc finish
(`shell`, whole-body `fillet`/`chamfer`) — those finishes are the #1 cause of
CAD-kernel crashes. Only fall back to multi-primitive CSG (`union`/`cut`) or a
finish op when NO single primitive fits.

Reason from the catalog (this is the principle, not a fixed lookup):
- a cup / bottle wall / tube → `hollow_cylinder` (NOT `cylinder` + `shell`)
- a bottle / vase / nozzle / any turned profile → `revolve` (NOT `cylinder` + `shell`)
- an open container / tray → `hollow_box` (NOT `box` + `shell`)
- a box with rounded edges → `filleted_box` (NOT `box` + a whole-body `fillet`)
- a cylinder with rounded ends → `rounded_cylinder` (NOT `cylinder` + a `fillet`)

### Catalog by function
- **Solids:** box, cylinder, sphere, cone, wedge, pyramid, prism, hexagon_prism,
  octagonal_prism, ellipsoid, capsule
- **Hollow / vessels:** hollow_cylinder, hollow_box, ring
- **Turned & lofted (non-boxy silhouettes):** revolve, profile_extrude,
  rect_to_round, rect_to_rect
- **Pre-finished (skip a separate finish op):** rounded_cylinder, filleted_box,
  chamfered_box

## Primitive Selection Rules

- Match the physical description to the closest schema in the `context["available_primitives"]` Rich Menu (which maps shape keys to descriptions).
- Once you select candidate shapes from the Rich Menu, write a **single python loop block** to call `lookup_primitive` for all of them in exactly one turn (e.g. `for s in ['cylinder', 'cone']: print(lookup_primitive(s))`). Do NOT do sequential, multi-turn lookups!
- **Get parameter NAMES exactly right.** If you are not 100% sure of a primitive's exact
  parameter names, `lookup_primitive(name)` FIRST — a wrong name is rejected as
  `primitive_gap` and costs a replan. Common traps: `torus` → `ring_radius` + `tube_radius`
  (NOT `radius`); `cone` → `base_diameter` + `top_diameter`; `hollow_cylinder` →
  `outer_radius` + `inner_radius`; `rect_to_round` → `base_length`/`base_width`/`top_diameter`.
- If NO single primitive fits, THEN use CSG: combine multiple primitives with
  `union` (add) and `cut` (subtract). Every `union` feature must OVERLAP its
  neighbour by ~0.5–1mm so the result fuses into ONE connected watertight solid
  (`num_components` == 1) — features that only touch stay disconnected.
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

> **Verify scale on complex parts**: after building a multi-feature/assembly
> plan, call `preview_plan(plan)` and read `num_components` (should be 1 for a
> connected part) and each feature's `pct_of_overall_bbox` — resize any feature
> that is too small to read, then FINAL. Skip this for a lone primitive.
>
> If a feature's realized `size_mm` is far SMALLER than you intended, you almost
> certainly used the WRONG primitive or wrong parameter NAMES (a param the
> primitive does not have is rejected/ignored) — fix the primitive or the param
> names, do not just enlarge. For a rectangle→round transition use `rect_to_round`;
> for a rectangular frustum use `rect_to_rect` (NOT `pyramid`, which tapers to a point).

---

## Non-boxy silhouettes: `profile_extrude` and `revolve`

When a part's cross-section is NOT a stock primitive — an L/T/U bracket, a cam,
a gear-ish outline, a channel — do NOT approximate it by stacking thin boxes.
Use `profile_extrude`: give it the closed 2D outline as `[[x, y], ...]` points
(mm, do not repeat the first point) and a `height` to extrude along +Z.

```json
{ "id": "bracket", "primitive": "profile_extrude", "operation": "base",
  "parameters": { "profile": [[0,0],[80,0],[80,10],[10,10],[10,60],[0,60]],
                  "height": 5.0 } }
```
That single step is a clean L cross-section (an 80×10 foot + a 10×60 leg)
extruded 5mm — one watertight solid, no tangent-face fusion risk.

### Turned vessels (bottle / cup / vase / flask / jar / nozzle / flange)
Any axisymmetric / turned part is ONE `revolve` of a closed 2D cross-section
profile (all `x >= 0`, swept about the Y axis, `angle` 360). A **walled** profile
— up the OUTER wall, across the top/rim, DOWN the INNER wall, across the floor —
gives the hollow interior in a SINGLE connected solid: no `shell`, no `union`, so
nothing can fail to fuse.

```json
{ "id": "bottle", "primitive": "revolve", "operation": "base",
  "parameters": { "angle": 360.0,
    "profile": [[0,0],[35,0],[35,150],[20,175],[20,200],
                [17.5,200],[17.5,175],[32.5,150],[32.5,3],[0,3]] } }
```
That profile is a 35mm-radius body rising to a 20mm-radius neck at z=200, then
back DOWN the 2.5mm inner wall to a 3mm floor — one hollow bottle, one solid.

ANTI-PATTERN — do NOT do this for a vessel: stack a `cylinder` body + `cylinder`
neck, `shell` to hollow, then `union` a separate `cap` cylinder. Unioning a solid
onto an already-shelled thin wall produces a fragile junction that does NOT fuse
→ disconnected components (`num_components` > 1) and a failed part. Use ONE
`revolve` instead.

**Hollow LAST (only if you truly cannot use `revolve`).** If a part genuinely
needs CSG + `shell`, union ALL solid features first, then apply `shell` ONCE at
the very end. NEVER `union` a solid onto an already-shelled wall.

Rule of thumb: if you find yourself unioning 3+ boxes to fake one flat outline,
replace them with ONE `profile_extrude`; if you're stacking cylinders + `shell`
to fake a vessel, replace them with ONE `revolve`. Preview_plan to confirm.

---

## FINISH STEP Schema

Finish steps act on the **whole accumulated body** (not a new primitive). Place them after all CSG steps.

> **Finish ops are a LAST RESORT.** `shell` and a whole-body `fillet`/`chamfer`
> are fragile and crash the CAD kernel on complex/stepped geometry. Before adding
> one, check whether a primitive already builds the feature: a hollow vessel →
> prefer `hollow_cylinder`/`hollow_box`/`revolve` over `shell`; a rounded box →
> prefer `filleted_box`/`chamfered_box` over a whole-body `fillet`/`chamfer`; a
> rounded cylinder → prefer `rounded_cylinder`. Reserve `shell`/whole-body fillet
> for a simple single-body shape where no primitive fits.

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
