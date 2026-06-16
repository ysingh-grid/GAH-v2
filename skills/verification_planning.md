# Skill: Verification Planning

This guide outlines how to define programmatic checks for generated shapes to ensure they match constraints before the vision verifier runs.

---

## Step 1 — Predict Theoretical Volume

Use these formulas to compute expected volume **before** generating code. Compare after `execute_cadquery` returns.

| Primitive | Volume Formula |
|---|---|
| box | `L × W × H` |
| cylinder | `π × R² × H` |
| cone (sharp) | `(1/3) × π × R_base² × H` |
| cone (frustum) | `(1/3) × π × H × (R1² + R1×R2 + R2²)` |
| sphere | `(4/3) × π × R³` |
| torus | `2 × π² × R_ring × R_tube²` |
| prism (n sides) | `(n × s² / (4 × tan(π/n))) × H` |
| hexagon_prism | `(3√3 / 2) × flat² × H` |
| hollow_cylinder | `π × H × (R_outer² - R_inner²)` |
| hollow_box | `(L×W×H) - (L-2t)×(W-2t)×(H-t)` (open top, wall t) |
| ellipsoid | `(4/3) × π × rx × rz²` (for 2-axis symmetry) |
| ring | `π × (R_outer² - R_inner²) × thickness` |
| pyramid | `(1/3) × L × W × H` |

**Tolerance rule**: Accept volume within ±15% of theoretical. Chamfers/fillets reduce volume slightly; this is normal.

---

## Step 2 — Predict Bounding Box

For every primitive, predict the expected `[xmin, xmax, ymin, ymax, zmin, zmax]` bounds.

**Rules**:
- `box(L, W, H)` centered at origin → `x: ±L/2`, `y: ±W/2`, `z: ±H/2`
- `cylinder(H, R)` centered at origin → `x: ±R`, `y: ±R`, `z: ±H/2`
- `cone` from `cq.Solid.makeCone(r1, r2, H)` → starts at `z=0`, ends at `z=H`. Translate by `-H/2` if centering is needed.
- Stacked primitives: track the total Z range from bottom of first to top of last.

Accept bbox within **±0.5mm** of predicted values.

---

## Step 3 — Face Count Reference

| Shape | Minimum Expected Faces |
|---|---|
| box | 6 |
| cylinder | 3 (top + bottom + side) |
| cone (sharp) | 2 (base + side surface) |
| cone (frustum) | 3 (bottom + top + side) |
| sphere | 1 |
| torus | 1 |
| hexagon_prism | 8 (6 sides + 2 caps) |
| hollow_box | 10+ |
| filleted_box / chamfered_box | 14+ |
| box with through-hole | 8+ |

If `faces_count` is dramatically lower than expected (e.g. `1` when expecting `6`), the CSG operation likely failed silently.

---

## Step 4 — Mesh Quality Thresholds (from `inspect_mesh`)

| Check | Pass Condition |
|---|---|
| `is_watertight` | True (or False only if apex singular edge) |
| `open_edges` | 0 (true boundary edges — exclude singular) |
| `singular_edges` | ≤ 1 (cone/pyramid apex allowed) |
| `volume_mm3` | > 0.0 |
| `passes` | True |

---

## Step 5 — Repair Trigger Logic

Trigger the **Repair Sub-Agent** if ANY of:
- `execute_cadquery.success == False`
- `inspect_mesh.passes == False`
- `volume_mm3 < V_theory × 0.5` (catastrophic volume loss → CSG failed)
- `faces_count < expected_min_faces`
