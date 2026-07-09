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

## Everything is ONE connected body — build the tree inline

This is a **single-object platform**: model the whole part as one CSG
construction tree you build yourself and `FINAL`. There is no hand-off and no
multi-body assembly (a bolt+nut or box+lid is out of scope).

Fix your own shared anchors first — every shared radius, plane, or bolt-circle
position, decided once and reused consistently across steps. Every `union`
feature must OVERLAP the body it joins by ~0.5–1mm (a feature that only touches —
tangent/coincident face — does NOT fuse; see `dimension_reasoning` Rule 2), so
the whole plan resolves to ONE connected watertight solid (`num_components` == 1).

**Wheel example** (one connected body): hub cyl r=15, rim ring inner=40/outer=44,
spoke spanning r=14..41 (overlaps hub & rim by ~1mm), polar ×5 — all as steps in
one plan: `[hub(base), spoke×5(union, pattern=polar), rim(union)]`.

> **Prefer a single rich primitive when one fits** (see `primitive_planning`): a
> hollow vessel is `hollow_cylinder`/`revolve`, not box/cylinder + a shell finish;
> a rounded box is `filleted_box`, not a whole-body fillet. Decompose into a CSG
> tree only when no single primitive expresses the shape.

> **Preview before FINAL** on a multi-feature plan: `ev = preview_plan(plan)`. If
> `ev["num_components"] > 1`, features only TOUCH — grow the overlaps ~1mm and
> re-preview until it fuses to one solid, then `FINAL`.
