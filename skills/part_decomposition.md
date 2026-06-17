---
name: part_decomposition
version: "1.0"
purpose: >
  Decompose a complex 3D shape described in a prompt into an ordered sequence
  of CSG operations on simple primitives (base → unions → cuts → finish).
  Used before primitive_planning to create the construction tree.
used_by:
  - planning_worker (Step 1.5 of W·01 — optional for complex shapes)
inputs:
  - user_prompt: "Raw natural-language design request"
  - intent: "Output of intent_extraction skill"
outputs:
  - construction_tree: "Ordered list of {id, role, primitive_type, operation} steps"
tags: [planning, CSG, decomposition, W01, phase1]
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
