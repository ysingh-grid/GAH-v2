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
| **Finish** | `fillet`/`chamfer`/`shell` | Applied last — stress relief, handling, appearance, hollowing |

> **Adapter/duct/pipe/tube/nozzle/manifold/funnel parts are NOT done after Base
> + Feature + Pocket.** If the part is meant to pass fluid, air, or a cable
> through it, a `shell` Finish step (or an equivalent hollow primitive/
> through-cut) is REQUIRED — see `primitive_planning`'s "Hollow / Flow-Through
> Parts" rule. A solid block shaped like the envelope is a silent defect: it
> looks correct from every exterior view and passes mesh checks.

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

## When to hand off vs design in one context

You have a way to hand a piece of the design off to be planned separately in
parallel. Use it when, and only when:

### Case A — Independent Solids (hand off)
Distinct bodies that only meet at an interface. Each designs freely in its own local frame.
- Cricket bat → `["blade", "handle"]`
- Bolt + nut → `["bolt", "nut"]`

### Case B — Features of One Connected Body (do NOT hand off — plan inline)
Hub+spokes+rim, flange+bolt-bosses+ribs. These are one connected body, not
independent solids — plan them yourself as a single construction tree
(`base` → `union` → `cut` → finish). Fix your own shared anchors first: every
shared radius, plane, or bolt-circle position, decided once and reused
consistently across steps. Every union feature must overlap the body it joins
by 0.5–1mm (a feature that only touches — tangent/coincident face — does NOT
fuse; see `dimension_reasoning` Rule 2).

**Wheel example** (Case B, plan inline): hub cyl r=15, rim ring inner=40/outer=44,
spoke spanning r=14..41 (overlaps hub & rim by ~1mm), polar ×5 — all as steps
in one plan: `[hub(base), spoke×5(union, pattern=polar), rim(union)]`.

### RULE: Only hand off for genuinely independent solids
A single connected body with many features — however many fillets, shells,
patterns, or holes — is NOT a hand-off case. Design it in one context. Only
a true multi-solid assembly (Case A) warrants a hand-off, and even then only
after you've fixed the shared anchors every piece must agree on.
