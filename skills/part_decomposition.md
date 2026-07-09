---
name: part_decomposition
version: "1.0"
purpose: >
  Decompose a complex 3D shape described in a prompt into an ordered sequence
  of CSG operations on simple primitives (base → unions → cuts → finish).
  Used before primitive_planning to create the construction tree.
used_by:
  - planner (decomposition step, for multi-primitive shapes)
inputs:
  - user_prompt: "Raw natural-language design request"
  - intent: "Output of intent_extraction skill"
outputs:
  - construction_tree: "Ordered list of {id, role, primitive_type, operation} steps"
tags: [planning, CSG, decomposition, phase1]
token_budget: low   # ~400 tokens — load only for multi-primitive shapes
---

# Skill: Part Decomposition

Decompose complex 3D geometry into a **CSG construction tree** before building
the PrimitivePlan. Used for multi-primitive shapes in **Phase 1**.

**Before decomposing from scratch, check the reference for a proven precedent.**
The reference includes past designs a user confirmed correct, keyed by their
original request. If one matches (or closely resembles) the current part, start
from its construction tree and adapt it — re-parametrise, add or drop features —
rather than re-deriving the whole tree. Reuse a known-good decomposition first.

Most complex mechanical parts follow this pattern:

```
Base Solid  (+addition solids)  (−subtraction solids)  [+finish features]
```

---

## Decomposition Roles

| Role | Operation | Description |
|---|---|---|
| **Base** | `base` | Largest/dominant primitive. Starting point. |
| **Feature** | `union` | Fused additions — bosses, ribs, tabs, flanges |
| **Pocket** | `cut` | Carved subtractions — holes, slots, pockets, counterbores |
| **Finish** | `fillet`/`chamfer` | Applied last — stress relief, handling, appearance |

---

## Decomposition Checklist

1. **Identify the Base Solid**
   - Largest dominant shape (e.g., main cylinder of a flange, main block of bracket)
   - Always the first step in the construction tree

2. **Identify Additions (Union)**
   - Fused protrusions: boss extrusions, ribs, lugs, tabs
   - Each becomes a `union` step with its own primitive

3. **Identify Pockets (Cut)**
   - Carved features: through-holes, blind pockets, slots, counterbores
   - Each becomes a `cut` step — remember to use the `+2mm / +1mm offset` rule

4. **Identify Finish Features**
   - Fillets, chamfers, shells
   - Always applied **after** all CSG is complete

---

## Example: Flanged Mount

| Step | Role | Primitive | Key Parameters |
|---|---|---|---|
| 1 | base | cylinder | outer_r=50, height=10 |
| 2 | union | cylinder | outer_r=25, height=30, z_offset=20 |
| 3 | cut | cylinder | outer_r=15, height=42, z_offset=-1 (hollow) |
| 4 | cut×4 | cylinder | r=3.3, height=12, radial=38 (mount holes) |
| 5 | finish | chamfer | 1mm on outer top edge |

> **Rule**: Build the construction tree first, then pass it to
> `primitive_planning` to assign library schemas and resolve all parameters.

---

## Independent solids vs. features of one body — both planned inline

Everything is ONE construction tree, planned by you, in one block. There is no
mechanism to hand a piece of the design off to be planned separately — the
distinction below is about how you REASON about anchors, not about who plans
what.

### Case A — Independent Solids
Distinct bodies that only meet at an interface, each free in its own local
frame until they need to align at that interface.
- Cricket bat → blade + handle
- Bolt + nut → bolt + nut

Fix the shared anchors first (thread diameter/pitch, the interface plane or
radius), THEN place every body's steps in your `steps` list — the first body
is `base`, every other body (even one that doesn't touch anything yet) is
`union`. A union of disjoint solids is legal; it produces one multi-component
compound. See `playbook`'s "EXACTLY ONE base step" rule.

### Case B — Features of One Connected Body
Hub+spokes+rim, flange+bolt-bosses+ribs. These are one connected body, not
independent solids — plan them as a single construction tree
(`base` → `union` → `cut` → finish). Fix your own shared anchors first: every
shared radius, plane, or bolt-circle position, decided once and reused
consistently across steps. Every union feature must overlap the body it joins
by 0.5–1mm (a feature that only touches — tangent/coincident face — does NOT
fuse; see `dimension_reasoning` Rule 2).

**Wheel example** (Case B): hub cyl r=15, rim ring inner=40/outer=44,
spoke spanning r=14..41 (overlaps hub & rim by ~1mm), polar ×5 — all as steps
in one plan: `[hub(base), spoke×5(union, pattern=polar), rim(union)]`.
