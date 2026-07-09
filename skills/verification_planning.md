---
name: verification_planning
version: "1.0"
purpose: >
  Define expected volume, bounding box, face count, and mesh quality thresholds
  BEFORE executing code, so that the verifier can detect silent CSG failures
  and trigger a replan at the right stage.
used_by:
  - planner (self-check step of every plan)
  - verifier (host-side — reference thresholds for the vision judge)
inputs:
  - primitive_plan: "PrimitivePlan dict with resolved parameters"
  - exec_result: "Output of execute_cadquery — volume_mm3, faces_count, bbox"
  - mesh_result: "Output of inspect_mesh — is_watertight, open_edges, passes"
outputs:
  - volume_theoretical_mm3: "Predicted volume from formula"
  - bbox_expected: "[xmin,xmax,ymin,ymax,zmin,zmax] in mm"
  - min_faces: "Minimum expected face count"
  - repair_triggered: "Boolean — whether the orchestrator should re-enter the planner"
tags: [verification, geometry, quality, phase3, phase4]
token_budget: low   # ~500 tokens — load for planning and verification
---

# Skill: Verification Planning

Pre-compute expected geometry metrics **before** code execution so failures
are caught immediately. Used in **Phases 3–4** of the pipeline.

---

## Step 1 — Predict Theoretical Volume

Compute expected volume **before** generating code. Compare against
`exec_result.volume_mm3` after execution.

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
| hollow_cylinder | `π × H × (R_outer² − R_inner²)` |
| hollow_box | `(L×W×H) − (L−2t)×(W−2t)×(H−t)` (open top, wall t) |
| ellipsoid | `(4/3) × π × rx × rz²` (2-axis symmetry) |
| ring | `π × (R_outer² − R_inner²) × thickness` |
| pyramid | `(1/3) × L × W × H` |
| ellipse_extrude | `π × x_radius × y_radius × height` |
| slot_extrude | `[(width − height) × height + π × (height/2)²] × depth` (stadium area × depth; `width`=slot length, `height`=slot diameter) |
| twist_extrude | `profile_area × height` — twisting shears the cross-section but does not change its area |

No closed form for `loft`, `loft_between`, `sweep`, `tube`, `helix_sweep`, `revolve`, `profile_extrude`, `arc_extrude`, `text_3d` — do NOT apply the Step 5 volume-ratio repair trigger to these; verify with bbox + `is_watertight` + `passes` only.

**Accept**: volume within **±15%** of theoretical.
(Chamfers/fillets reduce volume slightly — this is normal.)

---

## Step 2 — Predict Bounding Box

Predict `[xmin, xmax, ymin, ymax, zmin, zmax]` for each primitive:

- `box(L, W, H)` centered → `x: ±L/2`, `y: ±W/2`, `z: ±H/2`
- `cylinder(H, R)` centered → `x: ±R`, `y: ±R`, `z: ±H/2`
- `makeCone(r1, r2, H)` → starts at `z=0`, ends at `z=H`
  (translate by `−H/2` to center it)
- Stacked primitives → track total Z range: `[bottom_of_first, top_of_last]`
- `sweep` / `tube` / `helix_sweep` are PATH-DEFINED — their bbox comes from the
  path's own absolute `[x,y,z]` points, not from `position`; predict it from the
  path's extent, not from a base+height formula (see `dimension_reasoning`).

**Accept**: bbox within **±0.5mm** of predicted values.

---

## Step 3 — Face Count Reference

| Shape | Minimum Expected Faces |
|---|---|
| box | 6 |
| cylinder | 3 (top + bottom + curved side) |
| cone (sharp) | 2 (base + cone surface) |
| cone (frustum) | 3 (bottom + top + side) |
| sphere | 1 |
| torus | 1 |
| hexagon_prism | 8 (6 sides + 2 caps) |
| hollow_box | 10+ |
| filleted_box / chamfered_box | 14+ |
| box with through-hole | 8+ |
| revolve / profile_extrude / loft / taper_extrude / ellipse_extrude | 2 (caps) + 1 or more (side) — `smooth: true` fuses the whole side into ONE face regardless of profile-point count; `smooth: false` gives one face PER straight segment, so more control points = more faces |
| twist_extrude / slot_extrude / arc_extrude / loft_between | 3+ (varies with profile point/segment count) |
| tube / helix_sweep / sweep | 3+ (path-defined; face count tracks path complexity, not `position`) |

> **Alert**: If `faces_count` is dramatically lower than expected (e.g., `1`
> when expecting `6`), the CSG operation likely failed silently — UNLESS the
> primitive is `smooth: true` (revolve/profile_extrude/loft/…), where a single
> fused face is CORRECT and means the smooth spline surface worked, not a failure.

---

## Step 4 — Mesh Quality Thresholds

| Check | Pass Condition |
|---|---|
| `is_watertight` | `True` — or `False` **only** if apex singular edge (cone/pyramid) |
| `open_edges` | `0` (excluding singular apex edges) |
| `singular_edges` | `≤ 1` (cone/pyramid apex is allowed) |
| `volume_mm3` | `> 0.0` |
| `passes` | `True` |

---

## Step 5 — Repair Trigger Logic

Trigger a replan (the orchestrator re-enters the planner) if **any** of:

- `execute_cadquery.success == False`
- `inspect_mesh.passes == False`
- `volume_mm3 < V_theory × 0.5` (catastrophic volume loss → CSG failed)
- `faces_count < expected_min_faces` (silent solid failure)
