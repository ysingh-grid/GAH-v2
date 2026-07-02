---
name: compute_dimensions
version: "2.0"
purpose: >
  Teach an agent how to compute exact positions, clearances, volumes, and
  bounding boxes for every primitive in a CSG construction tree. This is the
  MATH of assembling primitives into a connected solid — centering conventions,
  half-height stacking, interference rules, and volume estimation. Self-contained
  and portable to any CAD geometry system.
inputs:
  - construction_tree: Output of decompose_and_select — ordered steps with primitive_type assignments
  - param_schemas: Parameter definitions for each primitive type (name, type, required, constraints)
outputs:
  - position_vectors: Corrected [x,y,z] center positions for each primitive
  - resolved_params: Numeric values for every required parameter
  - predicted_volume: Estimated total volume (for downstream verification)
  - predicted_bbox: Estimated bounding box [xmin, xmax, ymin, ymax, zmin, zmax]
tags: [geometry, dimensions, positioning, math, volume, portable]
token_budget: low
---

# Skill: Compute Dimensions

Turn a construction tree into a dimensioned plan by computing exact positions,
clearances, and volumes for every primitive. This is the math that turns
"a cylinder stacked on a box" into precise numeric coordinates.

---

## Rule 1 — Centering Conventions

Primitives place their geometry relative to a `position` point. Know which
convention your system uses:

| Convention | Typical Primitives | Behavior |
|---|---|---|
| **CENTERED** at position (all axes) | box, cylinder, sphere, ellipsoid, capsule, torus, hollow_box, chamfered_box, filleted_box, rounded_cylinder | To rest FLAT on XY plane (base at z=0): set `position.z = height/2` |
| **BASE at position** (extrudes UP from position) | ring, prism, hexagon_prism, octagonal_prism, hollow_cylinder, cone, pyramid, profile_extrude, revolve | `position.z = 0` sits these on the XY plane |

**Always check a primitive's description before placing it.** The convention
determines every stacking calculation that follows.

### CENTERED Primitive Behavior

A CENTERED cylinder of height `H` at position `(x, y, z)` spans:
- Z-range: `[z - H/2, z + H/2]`
- Radial range: `distance from (x,y) ≤ R` on XY plane

A CENTERED box of dimensions `(L, W, H)` at position `(x, y, z)` spans:
- X: `[x - L/2, x + L/2]`
- Y: `[y - W/2, y + W/2]`
- Z: `[z - H/2, z + H/2]`

---

## Rule 2 — Half-Height Stacking

When stacking one primitive ON TOP OF another:

```
body_top_z = body.position.z + body.height/2   (if CENTERED)
             OR
             body.position.z + body.height     (if BASE)

next_center_z = body_top_z + next.height/2     (if next is CENTERED)
                OR
                body_top_z                     (if next is BASE)
```

### Examples

**Cylinder on a box (both CENTERED):**
- Box: position `(0, 0, 0)`, `H_box = 10` → spans `z = [-5, +5]`
- Cylinder stack: `cyl_center_z = 5 + H_cyl/2`
  (top of box at +5, plus half the cylinder height)
- If `H_cyl = 30`: `cyl_center_z = 5 + 15 = 20`

**Cone on a cylinder (cylinder CENTERED, cone BASE):**
- Cylinder: position `(0, 0, 0)`, `H_cyl = 10` → top at `z = +5`
- Cone: position `(0, 0, 5)` (BASE convention — sits right on the top face)

---

## Rule 3 — Interference & Clearance Fits

### Through-Holes (cut operations)
Cutters must FULLY penetrate the body. A partial cut leaves a paper-thin film
→ disconnected geometry → mesh failure.

- Cutter height: `total_body_height + 1mm` (ensures pierce-through)
- Cutter position Z: centered so the cutter spans from slightly below the bottom
  to slightly above the top
  - If body spans `z = [0, T]` and cutter is CENTERED:
    `cutter.z = T/2`, `cutter.height = T + 1`

### Clearance Fits
Shaft diameter `D` → mating hole = `D + clearance`
- Standard clearance: 0.2–0.5mm
- M3 bolt → 3.2–3.3mm hole
- M6 bolt → 6.4–6.6mm hole (use 6.6mm for clearance fit)

### Union Overlap
Features being fused MUST extend INTO the body they join:
- **Minimum overlap**: 0.5mm into the body
- **Safe overlap**: 0.5–1mm
- A feature that only TOUCHES (tangent faces, coincident surfaces) does NOT fuse
  → disconnected components → mesh fails
- **Verify**: after all unions, the part must be ONE connected solid.
  Trace the overlap chain: every union feature must overlap something already
  attached to the base.

### Intersect Operations
`intersect` keeps only the shared volume (boolean AND) of the primitive and the
accumulated body. The intersecting primitive MUST overlap the body, or the result
is an empty solid → mesh fails.
- Use to carve a body to a shared region: box ∩ sphere = domed top,
  cylinder ∩ box = D-profile.

---

## Rule 4 — Volume Estimation (Canonical Formulas)

Predict volumes BEFORE building to catch silent CSG failures downstream.
These are the single source of truth for volume — all other skills reference
these formulas.

| Shape | Volume Formula | Notes |
|---|---|---|
| Box | `L × W × H` | |
| Cylinder | `π × R² × H` | R = radius, not diameter |
| Cone (sharp tip) | `(1/3) × π × R² × H` | R = base radius |
| Cone (frustum / truncated) | `(1/3) × π × H × (R₁² + R₁×R₂ + R₂²)` | R₁=R₂ → cylinder formula |
| Sphere | `(4/3) × π × R³` | |
| Torus | `2 × π² × R_ring × R_tube²` | R_ring = major radius to center of tube |
| Hollow cylinder | `π × H × (R_outer² − R_inner²)` | |
| Hollow box (open top) | `(L×W×H) − (L−2t)×(W−2t)×(H−t)` | wall thickness = t |
| Ellipsoid (2-axis symmetry) | `(4/3) × π × rx × rz²` | rx = equatorial, rz = polar |
| Ring (flat annular disk) | `π × (R_outer² − R_inner²) × thickness` | |
| Pyramid | `(1/3) × L × W × H` | |
| Prism (n-sided regular) | `(n × s² / (4 × tan(π/n))) × H` | s = side length |
| Hexagon prism | `(3√3 / 2) × flat² × H` | flat = flat-to-flat distance |

**For multi-primitive assemblies:**
- Add volumes for union steps
- Subtract volumes for cut steps (rough — doesn't account for partial overlap)
- Accept ±15% deviation from predicted volume (chamfers/fillets reduce volume slightly)
- Catastrophic mismatch (< 50% of predicted) = silent CSG failure → retry

---

## Rule 5 — Bounding Box Prediction

Predict the overall bounding box for quick sanity checks after execution:

Per-primitive (CENTERED convention):
- `box(L, W, H)` at `(0,0,0)` → `x: ±L/2, y: ±W/2, z: ±H/2`
- `cylinder(H, R)` at `(0,0,0)` → `x: ±R, y: ±R, z: ±H/2`
- `sphere(R)` at `(0,0,0)` → `x: ±R, y: ±R, z: ±R`

For stacked assemblies, track the envelope:
- X range: min over all primitives' x_min, max over all primitives' x_max
- Y range: same for y
- Z range: bottom of the first (lowest z) primitive to top of the last (highest z)

**Accept**: bbox within ±0.5mm of predicted values after execution.

---

## Worked Example: Stacked Cylinders

Construction: base cylinder (R=25, H=10) + shaft cylinder (R=12.5, H=30) on top.

### Position Calculation
- Base cylinder (CENTERED): position `(0, 0, 0)`
  - Spans z = [-5, +5]
  - Body top at z = +5
- Shaft cylinder (CENTERED):
  - `shaft_center_z = 5 + 30/2 = 20`
  - position `(0, 0, 20)`
  - Spans z = [5, 35]

### Volume
- Base: `π × 25² × 10 = 19,635 mm³`
- Shaft: `π × 12.5² × 30 = 14,726 mm³`
- Total: `34,361 mm³`

### Bounding Box
- X: [-25, +25] (max radius from base)
- Y: [-25, +25]
- Z: [-5, +35]