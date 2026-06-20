---
name: dimension_reasoning
version: "1.0"
purpose: >
  Resolve relative offsets, stack heights, clearance fits, and bounding
  dimensions so that generated CadQuery code places primitives correctly
  without overlaps, gaps, or non-manifold contact.
used_by:
  - planning_worker (Step 2+3 of W·01, integrated into primitive_planning)
  - repair_sub_agent (checking position math during repair)
inputs:
  - primitive_plan: "PrimitivePlan dict being constructed"
  - parameters: "Resolved numeric parameters for each primitive"
outputs:
  - position_vectors: "Corrected [x,y,z] center positions for each primitive"
  - validated_params: "Numeric parameters after engineering sanity check"
tags: [geometry, math, positioning, alignment, W01, phase1]
token_budget: low   # ~350 tokens body — load always
---

# Skill: Dimension Reasoning

Resolve stacking offsets, clearances, and coordinate positions for all
primitives **before** writing CadQuery code. This is integrated into
**Phase 1 / Steps 2–3**.

## Rule 1 — Center Points & Alignment

- CadQuery primitives (`box`, `cylinder`) are **centered at the workplane origin** by default.
- A cylinder of height `H` spans `z = -H/2` to `z = +H/2`.
- To sit a cylinder **on top of** a base flange of height `B` (centered at `z=0`):

  ```
  cylinder_center_z = B/2 + H_cylinder/2
  ```

- **Always track half-heights and half-lengths** to align faces flush.

## Rule 2 — Interference & Clearance Fits

- **Through-holes**: Make the cutter `H + 2mm` tall and offset by `1mm` outward
  to avoid zero-thickness skins (non-manifold errors).
- **Clearance fit**: If a shaft of diameter `D` fits into a hole, the hole
  diameter = `D + clearance` (typically `0.2mm` to `0.5mm`).
- **Union overlap**: Primitives being fused must overlap by **at least 0.1mm**
  — never place them perfectly flush (→ non-manifold).

## Rule 3 — Derived Parameters

Use these formulas to predict and verify shape volumes:

| Shape | Volume Formula |
|---|---|
| Box | `L × W × H` |
| Cylinder | `π × R² × H` |
| Cone (sharp) | `(1/3) × π × R_base² × H` |
| Sphere | `(4/3) × π × R³` |
| Hollow cylinder | `π × H × (R_outer² - R_inner²)` |
| Torus | `2 × π² × R_ring × R_tube²` |

Compare predicted volume to `execute_cadquery` output volume — accept ±15%.
