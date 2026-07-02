---
name: debug_cadquery
version: "2.0"
purpose: >
  Diagnose CadQuery compilation errors by matching a Python traceback to a known
  error category and applying the minimum targeted fix. Self-contained CadQuery
  v2 API reference and error catalog — portable to any CadQuery-based CAD system.
inputs:
  - broken_code: The CadQuery Python code that failed to execute
  - traceback: Full Python traceback / error message from the execution
  - current_params: The parameter values used in this attempt (for reference)
outputs:
  - fixed_code: Corrected Python code string
  - error_category: Which error type was matched
  - fix_description: What was changed and why
tags: [cadquery, debugging, errors, repair, code-generation]
token_budget: low
---

# Skill: Debug CadQuery Code

When CadQuery code fails, don't guess — match the traceback to a known error
category and apply the targeted fix. DO NOT rewrite the entire script; change
only what's broken.

---

## CadQuery v2 API Reference

CadQuery v2 has specific methods on `Workplane`. Know what exists and what doesn't:

| Shape | ✅ Correct API | ❌ DOES NOT EXIST |
|---|---|---|
| Box | `cq.Workplane("XY").box(length, width, height)` | |
| Cylinder | `cq.Workplane("XY").cylinder(height, radius)` | |
| Sphere | `cq.Workplane("XY").sphere(radius)` | |
| Wedge | `cq.Workplane("XY").wedge(dx, dy, dz, xmin, ymin, xmax, ymax)` | |
| Cone | `cq.Workplane("XY").add(cq.Solid.makeCone(radius1, radius2, height))` | `.cone()` |
| Torus | `cq.Workplane("XY").add(cq.Solid.makeTorus(ring_radius, tube_radius))` | `.torus()` |
| Polygon extrusion | `cq.Workplane("XY").polygon(n_sides, diameter).extrude(height)` | |
| Tapered extrusion | `cq.Workplane("XY").rect(l, w).extrude(h, taper=angle_deg)` | |
| Revolve | `cq.Workplane("XY").ellipseArc(rx, rz, 0, 180).close().revolve()` | |
| Fillet | `.fillet(radius)` on a solid or edges | |
| Chamfer | `.chamfer(length)` or `.chamfer(length, offset)` | |
| Shell | `.shell(edges_or_faces, thickness)` | |
| Hole | `.hole(diameter, depth)` — needs a selected face first | |
| Counterbore | `.cboreHole(diameter, cboreDiameter, cboreDepth, depth)` | |
| Countersink | `.cskHole(diameter, cskDiameter, cskAngle, depth)` | |

**Parameters for `makeCone`:**
- `radius1`: bottom radius (at z=0)
- `radius2`: top radius (can be 0 for a sharp tip)
- `height`: total height (cones start at z=0 and go to z=height — BASE convention)

**Parameters for `makeTorus`:**
- `ring_radius`: distance from origin to the center of the tube (major radius)
- `tube_radius`: radius of the tube cross-section (minor radius)

---

## Error Categories & Targeted Fixes

### Error 1 — `AttributeError: 'Workplane' has no attribute 'cone'` (or 'torus')

**Traceback signature:** `AttributeError` mentioning `.cone()` or `.torus()` on
a `Workplane` object.

**Root cause:** `.cone()` and `.torus()` are NOT methods on Workplane in CadQuery v2.
They must be created via `cq.Solid.makeCone()` / `cq.Solid.makeTorus()` and
added to the workplane.

**Fix:**
```python
# ❌ Broken
result = cq.Workplane("XY").cone(radius1=15, radius2=0, height=40)

# ✅ Fixed
result = cq.Workplane("XY").add(cq.Solid.makeCone(15, 0, 40))
```

---

### Error 2 — Fillet/Chamfer Radius Too Large

**Traceback signature:** `BRep_API: command not done` with `fillet` or `chamfer`
in the call stack, OR `OCP.Standard.Standard_ConstructionError` during a fillet
operation.

**Root cause:** The fillet/chamfer radius exceeds what the geometry can support.
A fillet cannot be wider than half the smallest adjacent face dimension.

**Fix — reduce the radius:**
```python
# Rule: fillet_val MUST be < half the smallest adjacent face dimension.
# For a filleted_box with height=4mm: max safe fillet_val ≈ 1.5 (< 4/2=2)
# Safe calculation: fillet_val = floor(min(height, width) / 2) - 0.5

# ❌ Broken — radius too large for thin geometry
result = result.fillet(3.0, result.edges())

# ✅ Fixed — radius adjusted to fit
result = result.fillet(1.5, result.edges())
```

**Heuristic:** `max_fillet_radius = min(smallest_dimension / 2.5, adjacent_edge_length)`

---

### Error 3 — Non-Manifold / Disconnected Bodies

**Traceback signature:** `BRep_API: command not done`, `Standard_ConstructionError`,
OR `Boolean operation failed` — but NOT during a fillet/chamfer (distinguish
from Error 2 by checking the stack trace).

**Root cause:** Bodies with faces that are exactly co-planar, tangent only (not overlapping),
or completely disjoint (no shared volume) cannot be boolean-combined.

**Fix for cuts (cutter doesn't fully intersect):**
```python
# Make the cutter extend beyond the body by 2mm total (1mm on each side)
# Example: body height = 10mm, cutter should be at least 12mm tall
cutter_height = body_height + 2
cutter = cq.Workplane("XY").cylinder(cutter_height, cut_radius)
```

**Fix for unions (features don't overlap the body):**
```python
# Ensure the feature extends INTO the body by at least 0.5mm
# If the body top is at z=5, the feature should start at z=4.5 or lower
feature_position_z = body_top_z - 0.5  # overlap into the body
```

---

### Error 4 — Empty Selector

**Traceback signature:** `IndexError` from `.faces(">Z")`, `.edges("|Z")`,
or similar CadQuery string selectors.

**Root cause:** The model was rotated/translated and the face is no longer
axis-aligned, OR the expected geometry doesn't exist after boolean operations.

**Fix options (try in order):**
1. Use direction-agnostic selectors:
   ```python
   # Instead of ">Z" (strict, requires face normal pointing in +Z direction)
   result.faces("#Z")  # matches any face with Z-parallel normal (either direction)
   ```
2. Select by geometry type:
   ```python
   result.faces("%Circle")  # all circular faces
   result.faces("%Plane")   # all planar faces
   ```
3. Fall back to index-based selection (least reliable — fragile to geometry changes):
   ```python
   result.faces().item(0)  # first face — use only as last resort
   ```

---

### Error 5 — Syntax / Import Errors

**Traceback signature:** `SyntaxError`, `NameError`, or `ImportError`.

**Standard imports — every CadQuery script needs:**
```python
import cadquery as cq
```

**Common pitfalls:**
- Missing closing bracket/parenthesis/quote
- Variable name typo (`makeCone` vs `makecone`)
- Using a variable before it's defined
- Forgot to assign the final result to the expected output variable

**Fix:** Check line-by-line for typos and import issues. These are rarely
CadQuery-specific; they're standard Python errors.

---

### Error 6 — Union/Cut Type Mismatch

**Traceback signature:** `AttributeError` or `TypeError` when calling
`.union()` / `.cut()` between incompatible types.

**Root cause:** Only Workplane objects can be combined with other Workplane
objects. A bare Solid or Shape cannot be `.union()`-ed directly onto a Workplane.

**Fix — wrap bare Solids in a Workplane:**
```python
# ❌ Broken — Solid can't be unioned directly onto Workplane
hole_shape = cq.Solid.makeCone(0, 5, 10)
result = result.cut(hole_shape)

# ✅ Fixed — wrap in Workplane first
hole_cutter = cq.Workplane("XY").add(cq.Solid.makeCone(0, 5, 10))
result = result.cut(hole_cutter)
```

---

## Repair Workflow

1. **Read the traceback** — identify the error category from the table above.
   Look at the LAST few lines of the traceback for the specific error type
   and the FIRST mention of a CadQuery operation for context.

2. **Apply the targeted fix** — change ONLY the broken line or parameter.
   Do not rewrite the entire script. A script that compiled before likely
   only has one issue.

3. **Check dependent code** — if you changed a variable name, radius, or
   position, verify that downstream code referencing that value is still
   consistent.

4. **Return the corrected code.** The fixed code should assign the final
   solid to the appropriate output variable.

---

## When One Fix Unmasks Another

Sometimes fixing the first error reveals a second one. That's expected — the
kernel stopped at the first failure. After applying a fix:

1. If the second error is in the same category (e.g., another `makeCone` call
   with the wrong signature), fix ALL instances in that category at once.

2. If the second error is in a different category (e.g., first was Error 1
   (API misuse), now Error 3 (non-manifold)), apply the fix for the new category.

3. Limit to 3 fix attempts per script. If still failing after 3 fixes,
   the root cause is structural (wrong CSG tree, fundamentally wrong approach)
   and the plan itself needs rethinking — not just code fixes.