---
name: dimension_reasoning
version: "1.0"
purpose: >
  Resolve relative offsets, stack heights, clearance fits, and bounding
  dimensions so the PrimitivePlan places primitives correctly without
  overlaps, gaps, or non-manifold contact once compiled.
used_by:
  - planner (dimensions/positioning step of every plan, and again on replan for
    cadquery_compile/cadquery_execute/mesh_repair feedback)
inputs:
  - primitive_plan: "PrimitivePlan dict being constructed"
  - parameters: "Resolved numeric parameters for each primitive"
outputs:
  - position_vectors: "Corrected [x,y,z] center positions for each primitive"
  - validated_params: "Numeric parameters after engineering sanity check"
tags: [geometry, math, positioning, alignment, phase1]
token_budget: low   # ~350 tokens body — load always
---

# Skill: Dimension Reasoning

Resolve stacking offsets, clearances, and coordinate positions for all
primitives **before** writing CadQuery code. This is integrated into
**Phase 1 / Steps 2–3**.

## Rule 1 — Center Points & Alignment

Primitives place their geometry relative to `position` in one of two ways:

| Convention | Primitives | Notes |
|---|---|---|
| **CENTERED** at `position` (all axes) | `box`, `cylinder`, `sphere`, `ellipsoid`, `capsule`, `torus`, `hollow_box`, `chamfered_box`, `filleted_box`, `rounded_cylinder` | To rest flat on XY plane (base at z=0): `position.z = height/2` |
| **BASE at `position`** (extrudes UP) | `ring`, `prism`, `hexagon_prism`, `octagonal_prism`, `hollow_cylinder`, `cone`, `pyramid`, `profile_extrude`, `revolve` | `position.z = 0` sits these on the plane |

Unsure for a specific primitive? Call `lookup_primitive(key)` and read its description before placing.

- A CENTERED cylinder of height `H` spans `z = position.z - H/2` to `z = position.z + H/2`.
- To sit a cylinder **on top of** a base of height `B` (centered at `z=0`):
  `cylinder_center_z = B/2 + H_cylinder/2`
- **Always track half-heights and half-lengths** to align faces flush.

## Rule 2 — Interference & Clearance Fits

- **Through-holes (cut)**: The cut primitive is CENTERED, so to pierce a body spanning
  `z=0..T` set `position.z = T/2` and `height = T + 1` (spans −0.5 to T+0.5).
  Never leave a paper-thin film — cuts must pass fully through.
- **Clearance fit**: Shaft of diameter `D` → hole diameter = `D + clearance` (0.2–0.5mm typical).
- **Union overlap**: Features being fused must extend **0.5–1mm INTO** the body they join.
  A feature that only touches (tangent/coincident face) does NOT fuse → disconnected components → mesh fails.
- **ONE connected solid**: After all unions the part must be a single connected body.
  Every union feature must overlap something already attached. Verify by tracing the overlap chain.
- **Intersect semantics**: `intersect` keeps only the boolean AND (shared volume) of the primitive
  and the accumulated body. The intersecting primitive must actually overlap the body or the result
  is an empty solid → mesh fails. Use intersect to carve a body to a shared region
  (e.g. box ∩ sphere = domed top, cylinder ∩ box = D-profile).

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
