# ForgeCAD Runtime Core

Compact API reference for normal `.forge.js` generation.

## Runtime

- ForgeCAD API globals are injected into every `.forge.js` script. Do not import, destructure, or redefine them.
- Do not use local variable names that shadow injected globals such as `chamfer`, `fillet`, `box`, `cylinder`, `union`, or `difference`.
- Scripts are sequential JavaScript and must return a renderable top-level value.
- Valid returns include `Shape`, `Sketch`, `ShapeGroup`, `Assembly`, `SolvedAssembly`, `SdfShape`, arrays of named renderables, or metadata objects containing renderables.
- Operations are immutable: every transform, boolean, or feature returns a new object.

## Parameters

```javascript
const width = param("Width", 50, { min: 20, max: 100, unit: "mm" });
```

Use `param()` for requested parametric models and for meaningful user-adjustable dimensions.

## Primitives and Placement

- `box(width, depth, height)`: rectangular solid centered on XY with base at `Z=0`.
- `cylinder(height, radius)`: cylinder centered on XY with base at `Z=0`.
- `sphere(radius)`: sphere centered at the origin.
- `torus(majorRadius, minorRadius)`: torus centered at the origin when available.

Center a ground-based primitive on all axes with:

```javascript
const centered = box(w, d, h).placeReference('center', [0, 0, 0]);
```

Prefer `placeReference('center', [0, 0, 0])` over manual Z centering when full XYZ centering is required.

## Shape Operations

- `shape.translate(x, y, z)`: move in millimeters.
- `shape.rotate([x, y, z], angleDeg)`: rotate around an axis by degrees.
- `shape.rotateX(angleDeg)`, `shape.rotateY(angleDeg)`, `shape.rotateZ(angleDeg)`: axis helpers when available.
- `shape.pointAlong([dx, dy, dz])`: orient cylinders or elongated parts along a vector before placement.
- `shape.placeReference(anchor, [x, y, z])`: align built-in or custom reference points.
- `shape.add(other)`: boolean union with another shape.
- `shape.subtract(other)`: boolean difference.
- `shape.intersect(other)`: boolean intersection.
- `group(...)`: preserve individual child identities instead of merging them into one solid.

## Sketches

- `rect(width, height)`: centered 2D rectangle.
- `circle2d(radius, segments?)`: centered 2D circle.
- `roundedRect(width, height, radius)`: centered rounded rectangle.
- `polygon([[x, y], ...])`: 2D polygon.
- `ngon(sides, radius)`: regular polygon by circumradius.
- `slot(length, width)`: oblong slot.
- `union2d(...)`, `difference2d(...)`, `intersection2d(...)`: batch sketch booleans.
- `sketch.extrude(height, options?)`: create a solid from a closed sketch.

## Edge Features

Tracked solid edge features are limited. They work on tracked vertical edges from `box()` or `Rectangle2D.extrude()` and may fail after booleans, shelling, cuts, generic extrudes, or tapered extrudes.

```javascript
let body = box(w, d, h);
body = chamferTrackedEdge(body, body.edge('vert-br'), size, [-1, -1]);
body = filletTrackedEdge(body, body.edge('vert-bl'), radius, [1, -1], 12);
```

Canonical quadrants:

- `vert-bl`: `[1, -1]`
- `vert-br`: `[-1, -1]`
- `vert-tr`: `[-1, 1]`
- `vert-tl`: `[1, 1]`

For "top edge" chamfers on boxes, consider modeling a chamfered cross-section with `polygon(...).extrude(...)` when all top edges need a reliable simple bevel.

## CLI and Export

The host MCP tool `write_and_export_forgecad_model(design_name, js_content)` writes `outputs/<design_name>/model.forge.js`, exports `outputs/<design_name>/model.stl`, and returns a schema-ready result. Use it unless debugging requires separate write/export calls.
