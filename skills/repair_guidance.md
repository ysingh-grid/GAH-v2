# Skill: Repair Guidance (Inner Loop)

This guide provides strategies for the Repair Sub-Agent to identify and fix python execution tracebacks and CadQuery API errors.

> **Sub-Agent Contract**: Always return ONLY the corrected code block. The final result must be assigned to the variable `result`.

---

## ⚠️ Critical API Reference (Commit this to memory)

CadQuery v2 does NOT have `.cone()` or `.torus()` as Workplane methods. Use the `cq.Solid` factory directly:

| Shape | Correct API |
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

## Common CadQuery Errors & Fixes

### 1. `AttributeError: 'Workplane' object has no attribute 'cone'`
The `.cone()` and `.torus()` methods do not exist on `Workplane`.
- **Fix**: Use `cq.Workplane("XY").add(cq.Solid.makeCone(r1, r2, h))` instead.

### 2. Non-Manifold Solid (`BRep_API: command not done`, `Standard_ConstructionError`)
Occurs when subtracting or unioning bodies whose faces are perfectly co-planar (zero-thickness contact) or are completely separate (disjoint).
- **Fix for cuts**: Make the cutter `2mm` taller than the target pocket, offset by `1mm` outside the face.
- **Fix for unions**: Ensure the primitives overlap by at least `0.1mm` before merging.

### 3. Empty Selector (`IndexError`, `.faces(">Z")` returned nothing)
Occurs when a face selector finds no geometry because the model was rotated or the selector direction is wrong.
- **Fix**: Use `.faces("#Z")` to find faces with a Z-normal regardless of sign, or use `.faces().item(0)` to select the first face by index.
- Double-check that no `.translate()` or `.rotate()` moved the solid so the expected face is no longer axis-aligned.

### 4. Syntax and Import Errors
- Always import cadquery at the top of the script: `import cadquery as cq`
- Match all open brackets and parentheses.
- String quotes must be consistent (`"XY"` not `'XY'` mixed mid-chain).

### 5. `.union()` / `.cut()` Shape Type Mismatch
Only `Workplane` objects can be unioned or cut with other `Workplane` objects.
- **Fix**: If using `cq.Solid.makeCone(...)` directly, wrap it first: `cq.Workplane("XY").add(solid)`.

---

## Repair Sub-Agent Workflow

1. Read the failing code and the traceback.
2. Identify the error line and category above.
3. Apply the targeted fix — do NOT rewrite the entire script.
4. Ensure the final corrected object is assigned to `result`.
5. Return ONLY the corrected Python script.
