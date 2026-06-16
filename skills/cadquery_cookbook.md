# Skill: CadQuery Cookbook

A practical cheat-sheet of CadQuery v2 code patterns for the Root RLM when compiling geometry from a PrimitivePlan.

> **Contract**: Every script must assign the final solid to a variable named `result`.
> Always import `cadquery as cq` at the top of the script.

---

## 1. Primitive Construction

```python
import cadquery as cq

# Box — centered at origin, 10×20×30
result = cq.Workplane("XY").box(10, 20, 30)

# Cylinder — centered at origin, radius 5, height 15
result = cq.Workplane("XY").cylinder(15, 5)

# Cone — radius1=15 (base), radius2=0 (sharp tip), height=45
# NOTE: Use cq.Solid.makeCone, NOT .cone()
result = cq.Workplane("XY").add(cq.Solid.makeCone(15.0, 0.0, 45.0))

# Frustum cone — base r=15, top r=5, height=30
result = cq.Workplane("XY").add(cq.Solid.makeCone(15.0, 5.0, 30.0))

# Sphere — radius 10
result = cq.Workplane("XY").sphere(10)

# Torus — ring radius 20, tube radius 4
# NOTE: Use cq.Solid.makeTorus, NOT .torus()
result = cq.Workplane("XY").add(cq.Solid.makeTorus(20.0, 4.0))

# Wedge
result = cq.Workplane("XY").wedge(20, 10, 15, 0, 0, 10, 5)

# Hexagonal prism — flat-to-flat=20, height=10 (circumscribed=True means flat-to-flat)
result = cq.Workplane("XY").polygon(6, 20, circumscribed=True).extrude(10)

# Hollow cylinder (tube) — outer r=10, inner r=7, height=20
result = cq.Workplane("XY").circle(10).circle(7).extrude(20)

# Tapered pyramid — 20×20 base tapering to a point over 30mm height
result = cq.Workplane("XY").rect(20, 20).extrude(30, taper=30.0)

# Ellipsoid — via revolve of a half-ellipse arc
result = cq.Workplane("XY").ellipseArc(10, 6, 0, 180).close().revolve()
```

---

## 2. Translate and Rotate

```python
# Translate a solid along Z by 25mm
result = cq.Workplane("XY").box(10, 10, 10).translate((0, 0, 25))

# Translate in X and Y
result = cq.Workplane("XY").cylinder(20, 5).translate((15, 0, 0))

# Rotate around Z axis by 45 degrees
result = cq.Workplane("XY").box(10, 5, 20).rotate((0,0,0), (0,0,1), 45)

# Rotate around X axis to lay a cylinder flat
result = cq.Workplane("XY").cylinder(30, 5).rotate((0,0,0), (1,0,0), 90)
```

---

## 3. CSG Operations (Union and Cut)

```python
# Union — fuse two solids together
base = cq.Workplane("XY").cylinder(10, 15)
cap  = cq.Workplane("XY").sphere(15).translate((0, 0, 5))
result = base.union(cap)

# Cut — subtract one solid from another (for holes, pockets, slots)
body = cq.Workplane("XY").box(40, 40, 20)
hole = cq.Workplane("XY").cylinder(22, 5).translate((0, 0, 0))
result = body.cut(hole)

# IMPORTANT: To prevent non-manifold singularities at cut boundaries,
# make the cutter 2mm taller and offset it 1mm beyond the face:
body = cq.Workplane("XY").box(40, 40, 20)
hole = cq.Workplane("XY").cylinder(22, 5).translate((0, 0, 1))  # 1mm offset
result = body.cut(hole)
```

---

## 4. Edge Finishing

```python
# Fillet all edges — radius 2mm
result = cq.Workplane("XY").box(20, 20, 20).fillet(2.0)

# Chamfer all edges — 1mm chamfer
result = cq.Workplane("XY").box(20, 20, 20).chamfer(1.0)

# Fillet only top face edges
result = cq.Workplane("XY").box(20, 20, 20).faces(">Z").edges().fillet(2.0)

# Fillet cylinder circular edges
result = cq.Workplane("XY").cylinder(30, 10).edges().fillet(1.0)
```

---

## 5. Stacking Pattern (Multiple Primitives)

Always compute center positions carefully when stacking:
```python
# Stack: base plate (H=5) + shaft (H=30)
# Base plate occupies Z: -2.5 to +2.5 (centered at origin)
# Shaft must be centered at Z = 2.5 + 15.0 = 17.5
base = cq.Workplane("XY").cylinder(5, 20)                  # H=5, centered at z=0
shaft = cq.Workplane("XY").cylinder(30, 8).translate((0, 0, 17.5))  # H=30, top of base
result = base.union(shaft)
```

---

## 6. Circular Hole Patterns

```python
import cadquery as cq
import math

body = cq.Workplane("XY").cylinder(10, 30)  # disc, H=10, R=30

# 4 mounting holes at radius=20, diameter=6
hole_radius = 3.0
radial_offset = 20.0
n_holes = 4
cutter = cq.Workplane("XY")
for i in range(n_holes):
    angle = 2 * math.pi * i / n_holes
    x = radial_offset * math.cos(angle)
    y = radial_offset * math.sin(angle)
    cutter = cutter.union(
        cq.Workplane("XY").cylinder(12, hole_radius).translate((x, y, 1))
    )
result = body.cut(cutter)
```
