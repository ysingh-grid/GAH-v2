---
name: decompose_and_select
version: "2.0"
purpose: >
  Teach an agent how to break any 3D object into an ordered CSG construction
  tree (base → unions → cuts → finish operations) and match each piece to the
  closest shape from a provided vocabulary. Self-contained — no system-specific
  references.
inputs:
  - user_request: Free-form natural-language description of the desired 3D shape
  - shape_vocabulary: List of available primitive shape names with one-line descriptions
outputs:
  - construction_tree: Ordered list of {id, role, primitive_type, operation} steps
  - unresolved_questions: List of facts that need clarification before planning
tags: [csg, decomposition, intent, portable, geometry-reasoning]
token_budget: low
---

# Skill: Decompose & Select

Break any 3D object described in natural language into an ordered CSG
construction tree and match each piece to the closest shape in your vocabulary.

---

## Phase 1 — Extract Intent

Before you decompose, extract the engineering requirements:

### 1. Primary Object
What is the target component? (bracket, gear, flange, bottle, spoon, wheel, etc.)

### 2. Dimension Classification
- **Explicit**: Stated directly — "height 45mm", "base diameter 30mm"
- **Implicit**: Derived from standards — "M6 bolt hole" → 6.6mm clearance diameter,
  "snug fit on 10mm shaft" → ~10.2mm bore
- **Variables**: Named parameters that may change (parametric design)

### 3. Constraints & Tolerances
- Fit requirements: clearance, press-fit, sliding fit
- Alignment: centered, flush, offset
- Material constraints: minimum wall thickness
- Functional features: mounting holes, chamfers for stress relief, pockets for weight

### 4. Unresolved Questions
Flag anything ambiguous. Better to ask than guess wrong:
- Missing dimensions ("how tall should the flange be?")
- Choice ambiguity ("M6 or M8 bolt holes?")
- Conflicting constraints ("can't be both 10mm thick AND lightweight shell")

---

## Phase 2 — Build the CSG Construction Tree

Almost every complex mechanical part follows this pattern:

```
Base Solid  →  Additions (union)  →  Subtractions (cut)  →  Finish Operations
```

### Decomposition Roles

| Role | Operation | Description |
|---|---|---|
| **Base** | `base` | The largest, most dominant primitive. Starting point of construction. |
| **Addition** | `union` | Fused protrusions — bosses, ribs, tabs, flanges, lugs |
| **Subtraction** | `cut` | Carved features — holes, slots, pockets, counterbores, shells |
| **Finish** | `fillet` / `chamfer` / `shell` | Applied LAST after all CSG — rounds, bevels, hollowing |

### Decomposition Checklist

1. **Find the Base**
   - What's the largest, most central shape?
   - Every construction tree starts with exactly one base.

2. **List Additions (union)**
   - What sticks OUT from the base? Protrusions, bosses, ribs, flanges.
   - Each becomes a separate union step.

3. **List Subtractions (cut)**
   - What's carved INTO the body? Through-holes, blind pockets, slots.
   - Remember the penetration rule: cutters must extend BEYOND the body surface
     to avoid paper-thin films (typically +1mm extra depth, centered to pierce fully).

4. **List Finish Operations**
   - Fillets, chamfers, shells — always AFTER all CSG is done.
   - Check: is the fillet radius small enough for the adjacent geometry?

### Construction Tree Format

Each step:
```
{ "id": unique_name, "role": base|addition|subtraction|finish,
  "operation": base|union|cut|fillet|chamfer|shell|hole,
  "primitive_type": shape_name_from_vocabulary,
  "key_params": [list of critical dimensions] }
```

---

## Phase 3 — Match Shapes to Vocabulary

For each step in the construction tree, pick the closest shape from the available
vocabulary:

### Selection Rules

1. **Match the physical description first**, not the name. "A rod" → cylinder.
   "A flat plate" → box. "A tapered column" → cone.

2. **If no single shape fits**, combine multiple primitives with union/cut.
   A "tube with square outer profile" → box (base) + cylinder (cut for the bore).

3. **Prefer exact matches** over approximate ones. A cone for a cone, not an
   approximation with stacked cylinders.

4. **If nothing fits cleanly, say so.** Don't fake it with a wrong shape —
   flag it as an unresolved question. The downstream planner needs to know
   when the vocabulary is insufficient.

### Vocabulary-Driven Selection

Given a list like `["box", "cylinder", "cone", "sphere", "torus", ...]`:
```
"rectangular block"       → box
"shaft" / "rod" / "pin"  → cylinder
"tapered column" / "cone"→ cone
"ball" / "dome"          → sphere
"donut" / "ring shape"   → torus
```

---

## Phase 4 — When to Delegate vs. Design Inline

### Case A — Independent Solids (Delegate)
Separate bodies that only meet at an interface. Each designs freely in its own
local frame.
- Examples: box + lid, bolt + nut, cricket bat blade + handle
- Fix shared anchors FIRST (radii, bolt-circle positions, overlap amounts),
  then design each solid independently.

### Case B — Connected Body Features (Design Inline)
One connected body with many features. Plan it yourself as a single tree.
- Examples: hub+spokes+rim, flange+bolt-bosses+ribs
- Rule: fix shared anchors once (every shared radius, plane, bolt-circle position),
  reuse consistently across steps.
- Every union feature MUST overlap the body it joins by 0.5–1mm.
  A feature that only touches (tangent/coincident face) does NOT fuse.

**Single connected body = single construction tree. Don't over-delegate.**

---

## Worked Example: Flanged Mount

Request: "A 50mm circular flange, 10mm thick, with a 25mm diameter shaft extending
30mm up, bored through with a 15mm hole, and 4 M3 clearance mount holes on a 38mm
bolt circle."

Vocabulary: box, cylinder, cone, sphere, torus

### Intent Extraction
- Target: flanged mount (flange base + shaft + bore + mount holes)
- Explicit dims: flange dia=50, flange h=10, shaft dia=25, shaft h=30, bore dia=15
- Implicit: M3 clearance → 3.3mm hole diameter, bolt circle radius=38mm
- Constraint: bore passes fully through both shaft AND flange

### Construction Tree

| Step | Role | Operation | Primitive | Key Parameters |
|---|---|---|---|---|
| 1 | base | base | cylinder | dia=50, h=10 |
| 2 | addition | union | cylinder | dia=25, h=30, stacked on top |
| 3 | subtraction | cut | cylinder | dia=15, pierce through full height |
| 4 | subtraction | cut | cylinder (×4) | dia=3.3, polar pattern at r=38 |
| 5 | finish | chamfer | — | 1mm on shaft top edge |

---

## Output Contract

After completing all phases, return:

1. A construction tree — ordered list of steps with primitive_type assignments
2. Any unresolved questions that need user clarification

This output feeds into the dimension computation stage (see `compute_dimensions`
skill for centering rules, clearance formulas, and stacking math).