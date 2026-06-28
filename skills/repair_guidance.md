---
name: repair_guidance
version: "1.0"
purpose: >
  Help the Repair Sub-Agent identify the root cause of a CadQuery execution
  traceback and apply the minimal targeted fix to produce valid, compilable code.
used_by:
  - repair_sub_agent (W·01 inner repair loop, max 3 attempts)
inputs:
  - broken_code: "The Python code string that failed"
  - traceback: "Full Python traceback / error message from execute_cadquery"
  - primitive_plan: "PrimitivePlan dict for parameter reference"
outputs:
  - fixed_code: "Corrected Python code string assigning final solid to `result`"
tags: [repair, debugging, cadquery, errors, W01, inner-loop]
token_budget: medium  # ~600 tokens — load only when repair is triggered
sub_agent_contract: >
  Return ONLY the corrected Python code string.
  No markdown fences, no explanations.
  Final solid MUST be assigned to `result`.
---

# Skill: Repair Guidance (Inner Loop)

Fix CadQuery execution errors. This is used by the **Repair Sub-Agent**
inside the **W·01 inner repair loop** (max 3 attempts).

> **Contract**: Return ONLY the corrected Python code. No markdown, no prose.
> The fixed code MUST assign the final solid to `result`.

---

## ⚠️ Critical API Reference

CadQuery v2 does **NOT** have `.cone()` or `.torus()` as Workplane methods.

| Shape | ✅ Correct API |
|---|---|
| Box | `cq.Workplane("XY").box(length, width, height)` |
| Cylinder | `cq.Workplane("XY").cylinder(height, radius)` |
| Sphere | `cq.Workplane("XY").sphere(radius)` |
| Wedge | `cq.Workplane("XY").wedge(dx, dy, dz, xmin, ymin, xmax, ymax)` |
| **Cone** | `cq.Workplane("XY").add(cq.Solid.makeCone(radius1, radius2, height))` |
| **Torus** | `cq.Workplane("XY").add(cq.Solid.makeTorus(ring_radius, tube_radius))` |
| Polygon extrusion | `cq.Workplane("XY").polygon(n_sides, diameter).extrude(height)` |
| Tapered extrusion | `cq.Workplane("XY").rect(l, w).extrude(h, taper=angle_deg)` |
| Revolve | `cq.Workplane("XY").ellipseArc(rx, rz, 0, 180).close().revolve()` |

---

## Common Errors & Targeted Fixes

### Error 1 — `AttributeError: 'Workplane' has no attribute 'cone'`
`.cone()` and `.torus()` don't exist on Workplane.
- **Fix**: `cq.Workplane("XY").add(cq.Solid.makeCone(r1, r2, h))`

### Error 2 — Fillet/chamfer radius too large (`BRep_API: command not done` inside `.fillet()`)
Traceback shows `in fillet` in the call stack. The fillet radius exceeds the geometry.
- **Rule**: `fillet_val` MUST be < half the smallest adjacent face dimension.
  For a `filleted_box` with `height=4`, max safe `fillet_val` ≈ 1.5 (< 4/2=2).
- **Fix in the plan**: Reduce `fillet_val` in the `filleted_box` parameters:
  `fillet_val = floor(min(height, width) / 2) - 0.5` (e.g. height=4 → fillet_val=1.5).
- **Fix in code**: Lower the radius passed to `.fillet(radius, ...)`.
- **Distinguish from Error 3**: if `in fillet` is in the traceback, use THIS fix first.

### Error 3 — Non-Manifold (`BRep_API: command not done`, `Standard_ConstructionError`)
Bodies whose faces are exactly co-planar or completely disjoint. Traceback does NOT show `in fillet`.
- **Fix for cuts**: Make cutter `2mm` taller, offset `1mm` outward.
- **Fix for unions**: Ensure overlap ≥ `0.1mm` before `.union()`.

### Error 5 — Empty Selector (`IndexError` from `.faces(">Z")`)
The model was rotated/translated and the face is no longer axis-aligned.
- **Fix**: Use `.faces("#Z")` (Z-normal regardless of sign) or `.faces().item(0)`.

### Error 6 — Syntax / Import Errors
- Always `import cadquery as cq` at the top.
- Match all brackets and quotes consistently.

### Error 7 — `.union()` / `.cut()` Type Mismatch
Only `Workplane` objects can be combined with other `Workplane` objects.
- **Fix**: Wrap bare Solids: `cq.Workplane("XY").add(cq.Solid.makeCone(...))`.

---

## Repair Workflow

1. Read traceback → identify error category above.
2. Apply the **targeted** fix — do NOT rewrite the whole script.
3. Ensure final solid is assigned to `result`.
4. Return ONLY the corrected Python script.
