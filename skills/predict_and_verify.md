---
name: predict_and_verify
version: "2.0"
purpose: >
  Teach an agent to predict geometric properties (volume, bounding box, face
  count) BEFORE executing code, then compare predictions against actual results
  to detect silent CSG failures, disconnected components, or degenerate geometry.
  Self-contained — portable to any CAD geometry system that produces solid models.
inputs:
  - construction_tree: Ordered steps with resolved parameters and positions
  - volume_formulas: Reference the canonical formulas in compute_dimensions skill
outputs:
  - predicted_volume_mm3: Estimated total solid volume
  - predicted_bbox: Expected bounding box [xmin, xmax, ymin, ymax, zmin, zmax]
  - min_expected_faces: Minimum face count for the shape
  - pass_rules: Thresholds that define geometric validity
tags: [verification, geometry, quality, prediction, portable]
token_budget: low
---

# Skill: Predict & Verify

Predict the expected geometric properties BEFORE building, then use those
predictions after execution to catch failures immediately. A bad mesh that
slips through wastes time and tokens on downstream verification.

---

## Step 1 — Predict Volume

Compute total expected volume from the resolved parameters. Reference the
canonical formulas in the `compute_dimensions` skill for your primitive
shapes.

For multi-step assemblies:
- Base: compute its volume directly
- Additions (union): ADD their volumes
- Subtractions (cut): SUBTRACT their cutter volumes (approximate — cuts may
  only partially overlap, but the estimate is sufficient for failure detection)
- Finish features (fillets/chamfers): subtract 2-5% from the total (they
  remove material)

### Volume Acceptance Thresholds

| Condition | Interpretation |
|---|---|
| Actual within ±15% of predicted | ✅ Normal — fillets/chamfers reduce volume slightly |
| Actual > 15% below predicted | ⚠️ Possible CSG failure — a union didn't fuse, or a part was lost |
| Actual < 50% of predicted | 🔴 Catastrophic — most of the solid is missing, CSG failed entirely |
| Actual > 15% above predicted | ⚠️ A cut didn't execute, or duplicate geometry was created |

---

## Step 2 — Predict Bounding Box

For each primitive in the construction tree, determine its extent in X, Y, Z
space. Combine to get the overall envelope.

### Per-Shape Bounds (CENTERED convention, at position (0,0,0))

| Shape | X bounds | Y bounds | Z bounds |
|---|---|---|---|
| Box (L, W, H) | ±L/2 | ±W/2 | ±H/2 |
| Cylinder (H, R) | ±R | ±R | ±H/2 |
| Sphere (R) | ±R | ±R | ±R |
| Cone (R₁, R₂, H) — BASE convention | — | — | base starts at position.z, top at position.z+H |

For cones/rings/prisms using BASE convention: adjust according to their
actual positioning, accounting for the offset from the base.

### Stacked Assembly Envelope

```
xmin = min(all_primitives_x_min_positions)
xmax = max(all_primitives_x_max_positions)
ymin = min(all_primitives_y_min_positions)
ymax = max(all_primitives_y_max_positions)
zmin = min(all_primitives_z_min_positions)
zmax = max(all_primitives_z_max_positions)
```

### Bounding Box Acceptance

Accept bounding box dimensions within **±0.5mm** of predicted values.
A larger deviation suggests a rotation error or a primitive placed at the
wrong position.

---

## Step 3 — Predict Face Count

Face count is a strong signal for CSG success. A dramatically wrong face
count = a primitive didn't fuse or a boolean operation was silently skipped.

| Shape | Minimum Expected Faces | Typical Faces |
|---|---|---|
| Box | 6 | 6 |
| Cylinder | 3 | 3 (top disk + bottom disk + curved wall) |
| Cone (sharp, BASE) | 2 | 2 (base disk + conical surface) |
| Cone (frustum, BASE) | 3 | 3 (bottom disk + top disk + conical surface) |
| Sphere | 1 | 1 (single closed surface) |
| Torus | 1 | 1 |
| Hexagon prism | 8 | 8 (6 sides + 2 caps) |
| Hollow box (open top, wall t) | 10+ | ~14 |
| Filleted box / Chamfered box | 14+ | ~26 |
| Box with one through-hole | 8+ | ~10 |
| Box with multiple through-holes | 6 + (2 × N_holes) | Varies |

**Alert rules:**
- `actual_faces == 1` when expecting 6+ → the CSG tree collapsed to a single
  surface. The boolean operations failed silently — most likely a cut or union
  that didn't register.
- `actual_faces < min_expected` → at least one primitive in the tree didn't
  contribute to the final solid. Check union overlaps and cut penetration depths.
- `actual_faces >> expected` (e.g., 50 when expecting 8) → the mesh is
  over-tessellated, or a geometry kernel error produced degenerate faces. May
  still be valid, but worth flagging.

---

## Step 4 — Mesh Quality Checks

After execution, run these checks on the resulting mesh:

| Check | Pass Condition | When Failure Is Acceptable |
|---|---|---|
| Watertight | `True` | Singular apex edges: cones with sharp tips (R₂=0) and pyramids have ONE singular edge at the apex — this is geometrically correct, not a hole. If `open_holes == 1` AND the shape is a cone/pyramid with a sharp tip, accept it. |
| Open edges | 0 | See watertight exception above |
| Self-intersections | 0 | Never acceptable — always requires repair |
| Connected components | 1 | Must be one connected solid — multiple components = a union didn't fuse |
| Volume | `> 0.0` | Zero volume = the solid degenerated |
| Overall passes | `True` | Watertight AND zero self-intersections AND single component |

---

## Step 5 — When To Trigger A Retry

An agent should re-plan/rebuild if ANY of these conditions are true:

1. **Code execution failed** — the geometry kernel raised an error during
   construction (compile error, parameter out of range, unsupported operation).

2. **Mesh inspection failed** — not watertight, has self-intersections, or
   more than one connected component (with the apex exception noted above).

3. **Volume catastrophe** — actual volume < 50% of predicted. This means at
   least one major primitive in the construction tree didn't contribute.

4. **Face count anomaly** — actual face count < minimum expected. A boolean
   operation (union/cut) was silently skipped.

5. **Bounding box drift** — actual bbox deviates > 2mm from predicted in any
   axis. Suggests a positioning or rotation error.

### Retry Discipline

- Read the error/failure message FIRST. Identify which specific parameter or
  operation caused the failure.
- Change ONLY what's broken. Don't re-derive the entire design from scratch.
- If the same failure repeats after changing a parameter, the root cause is
  different from what you assumed — re-examine the error message.
- After 3 identical failures: stop and flag the design as needing a different
  approach (the vocabulary may be insufficient).

---

## Worked Example: Flanged Mount

Construction: base cylinder (R=25, H=10) + shaft cylinder (R=12.5, H=30) +
through-bore cylinder (R=7.5 cut) + 4× M3 mount holes (R=1.65 each, cut).

### Predicted Volume
- Base: π × 25² × 10 = 19,635 mm³
- Shaft: π × 12.5² × 30 = 14,726 mm³
- Bore (cut): −π × 7.5² × 41 = −7,246 mm³  (note: cutter H = total body H + 1)
- Holes (cut): −4 × π × 1.65² × 10 = −342 mm³
- **Predicted total**: 26,773 mm³  (±15% range: 22,757 – 30,789 mm³)

### Predicted Bounding Box
- X: [-25, +25] (base radius dominates)
- Y: [-25, +25]
- Z: [-5, +35] (base bottom to shaft top)

### Predicted Min Faces
- Base cylinder: 3
- Shaft cylinder (union): +3
- Bore cylinder (cut): adds 3 internal faces
- 4× mount holes (cut): adds ~8 internal faces
- **Minimum expected**: ~17 faces (slightly more for hole intersections)
- 🚨 If actual = 3 or 6: the bore and/or mount hole cuts failed entirely.