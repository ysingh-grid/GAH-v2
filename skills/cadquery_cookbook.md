---
name: cadquery_cookbook
version: "1.1"
purpose: >
  Reference cheat-sheet of correct CadQuery v2 API patterns for every
  supported primitive and operation. The code generator MUST follow these
  patterns exactly — no improvisation.
used_by:
  - planning_worker (Step 4 — code generation)
  - repair_sub_agent (Step 5 — repair loop)
  - refine_sub_agent (outer refinement loop)
inputs:
  - primitive_plan: "PrimitivePlan dict with resolved parameters"
outputs:
  - cadquery_code: "Python code string assigning final solid to `result`"
tags: [codegen, cadquery, API, patterns, W01, phase2]
token_budget: medium  # ~900 tokens — load for codegen and repair only
contract: >
  Every script MUST:
  1. Start with `import cadquery as cq`
  2. Assign the final solid to a variable named `result`
  3. Use ONLY the API patterns listed below — no undocumented methods
---

# Skill: CadQuery Cookbook

Authoritative CadQuery v2 code patterns. The code generator **must** follow
these exactly. This is **Phase 2** of the RLM pipeline.

> **Contract**: Every script must assign the final solid to `result`.
> Always `import cadquery as cq` at the top.

---

## 1. Primitive Construction

```python
import cadquery as cq

# Box — centered at origin, length × width × height
result = cq.Workplane("XY").box(10, 20, 30)

# Cylinder — height first, then radius
result = cq.Workplane("XY").cylinder(15, 5)

# Cone (sharp tip) — radius1=base, radius2=0, height
# ⚠️ NO .cone() method on Workplane — use cq.Solid.makeCone
result = cq.Workplane("XY").add(cq.Solid.makeCone(15.0, 0.0, 45.0))

# Frustum cone — base r=15, top r=5, height=30
result = cq.Workplane("XY").add(cq.Solid.makeCone(15.0, 5.0, 30.0))

# Sphere — radius
result = cq.Workplane("XY").sphere(10)

# Torus — ring radius, tube radius
# ⚠️ NO .torus() method on Workplane — use cq.Solid.makeTorus
result = cq.Workplane("XY").add(cq.Solid.makeTorus(20.0, 4.0))

# Wedge
result = cq.Workplane("XY").wedge(20, 10, 15, 0, 0, 10, 5)

# Hexagonal prism — flat-to-flat diameter, height (circumscribed=True)
result = cq.Workplane("XY").polygon(6, 20, circumscribed=True).extrude(10)

# Hollow cylinder (tube) — outer circle, inner circle, extrude
result = cq.Workplane("XY").circle(10).circle(7).extrude(20)

# Tapered pyramid — rect base tapering to a point
result = cq.Workplane("XY").rect(20, 20).extrude(30, taper=30.0)

# Ellipsoid — revolve a half-ellipse arc
result = cq.Workplane("XY").ellipseArc(10, 6, 0, 180).close().revolve()
```

---

## 2. Translate and Rotate

```python
# Translate along Z by 25mm
result = cq.Workplane("XY").box(10, 10, 10).translate((0, 0, 25))

# Translate in X and Y
result = cq.Workplane("XY").cylinder(20, 5).translate((15, 0, 0))

# Rotate around Z axis by 45°
result = cq.Workplane("XY").box(10, 5, 20).rotate((0,0,0), (0,0,1), 45)

# Rotate around X axis — lay cylinder flat
result = cq.Workplane("XY").cylinder(30, 5).rotate((0,0,0), (1,0,0), 90)
```

---

## 3. CSG Operations (Union / Cut)

```python
# Union — fuse two solids (must overlap by ≥ 0.1mm)
base = cq.Workplane("XY").cylinder(10, 15)
cap  = cq.Workplane("XY").sphere(15).translate((0, 0, 5))
result = base.union(cap)

# Cut — subtract (cutter must be 2mm taller, offset 1mm)
body = cq.Workplane("XY").box(40, 40, 20)
hole = cq.Workplane("XY").cylinder(22, 5).translate((0, 0, 1))  # 1mm offset ↑
result = body.cut(hole)
```

---

## 4. Edge Finishing

```python
# Fillet ALL edges — radius 2mm
result = cq.Workplane("XY").box(20, 20, 20).fillet(2.0)

# Chamfer ALL edges — 1mm
result = cq.Workplane("XY").box(20, 20, 20).chamfer(1.0)

# Fillet only top face edges
result = cq.Workplane("XY").box(20, 20, 20).faces(">Z").edges().fillet(2.0)

# Fillet cylinder circular edges
result = cq.Workplane("XY").cylinder(30, 10).edges().fillet(1.0)
```

---

## 5. Stacking (Multiple Primitives)

Compute center positions using the half-height rule from `dimension_reasoning`:

```python
# Base plate H=5, shaft H=30 sitting on top
# Base: z ∈ [-2.5, +2.5]  →  Shaft center: z = 2.5 + 15.0 = 17.5
base  = cq.Workplane("XY").cylinder(5, 20)
shaft = cq.Workplane("XY").cylinder(30, 8).translate((0, 0, 17.5))
result = base.union(shaft)
```

---

## 6. Circular Hole Patterns

```python
import cadquery as cq
import math

body = cq.Workplane("XY").cylinder(10, 30)   # disc H=10, R=30

# 4 mounting holes Ø6 at radial offset 20mm
n_holes, hole_r, radial = 4, 3.0, 20.0
cutter = cq.Workplane("XY")
for i in range(n_holes):
    angle = 2 * math.pi * i / n_holes
    x, y  = radial * math.cos(angle), radial * math.sin(angle)
    cutter = cutter.union(
        cq.Workplane("XY").cylinder(12, hole_r).translate((x, y, 1))
    )
result = body.cut(cutter)
```
