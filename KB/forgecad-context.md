# ForgeCAD — AI Context (Chat UI)

> **Usage:** Paste this file as context into your AI chat session (Claude.ai, ChatGPT, Gemini, etc.).
> The AI will have full ForgeCAD API knowledge and will guide you through building models.
>
> **No CLI access in this session.** The AI cannot run commands directly. Instead, it will ask
> you to run commands like `forgecad run <file>`
> in your terminal and paste back the output for verification and iteration.

## Workflow

1. Tell the AI what you want to build and share any existing `.forge.js` files.
2. The AI will write or edit model files for you.
3. To validate, run `forgecad run <file>` in your terminal and paste the output.
4. Iterate until the model looks right, then optionally `forgecad render 3d <file>` for a PNG.

---

## ForgeCAD API Reference

Author or modify ForgeCAD models, sketches, assemblies, and CLI workflows.
Prefer documented primitives, import rules, and placement strategies over inventing new APIs.

### Model files

- `.forge.js` — parametric part or assembly script; return a `Shape`, `Sketch`, `ShapeGroup`, `Assembly`, `SolvedAssembly`, array of renderables, or metadata object. Assemblies render directly; do not add `.toGroup()` unless you need `ShapeGroup` behavior.
- Model the physical artifact, not an educational diagram. Do not add explanatory labels, arrows, legends, or text plaques unless the user explicitly asks for a presentation or teaching view. Product markings are allowed only when they would exist on the real object.
- Build the real closed CAD first. Do not bake cutaways, sectioned shells, permanently exploded layouts, or hidden-parts views into the default model just to show internals. Use viewer-only cut planes, `explodeView`, object hiding, transparency, or `inspect sections` after the artifact exists.

### Import and composition

- Always include the extension in relative imports: `require("./file.forge.js", { Param: value })` for model files and `require("./helpers.js")` for plain helper modules. Do not write extensionless imports such as `require("./file")`; ForgeCAD resolves project imports by exact path.
- ForgeCAD APIs are injected globals in `.forge.js` files. Use `bom()`, `box()`, `scene()`, `Shape`, etc. directly; do not destructure those names from helpers with patterns like `const { bom } = require("./bom.js")`. If a helper file is needed, import it under a project-specific name such as `const bomHelpers = require("./bom.js")`.
- `importSvgSketch()` for SVG files (file format loader, not a module import).
- `.placeReference('bottom', [0,0,0])` to align any built-in anchor to a world coordinate; also works with custom `.withReferences()`.
- Plain `.js` modules for shared helpers/constants (not model imports).

### Validation commands (ask the user to run these)

```
forgecad run <file.forge.js>                          # geometry diagnostics
forgecad render 3d <file.forge.js>                    # PNG render (shaded 3D)
forgecad render wireframe <file.forge.js>             # wireframe-only render
forgecad render section <file.forge.js> --plane XZ    # 2D cross-section (SVG/PNG)
forgecad capture gif <file.forge.js>                  # animated orbit GIF
```

---

<!-- skill-cli.md -->

# ForgeCAD CLI for AI Workflows

Use the CLI to validate, inspect, and export the model the AI is editing. Keep commands generic so they apply to the user's file, not a repo demo.

## Validation Loop

```bash
forgecad run path/to/model.forge.js
forgecad run path/to/model.forge.js --debug-imports
forgecad run path/to/model.forge.js --backend occt
forgecad check print path/to/model.forge.js --json
```

- `forgecad run` prints geometry diagnostics, object summaries, collisions, verification results, and solver info.
- `forgecad check print` reports collisions, mesh health, sampled walls, overhangs, and bed contact.
- Use `forgecad run -p "Name=Value"` when you need to validate a specific parameter value.

## Visual Checks

```bash
forgecad render 3d path/to/model.forge.js
forgecad render 3d path/to/model.forge.js --camera front --camera iso
forgecad render wireframe path/to/model.forge.js
forgecad render section path/to/model.forge.js out/section.svg --plane XZ --offset 10
forgecad capture gif path/to/model.forge.js
```

- Use `render 3d` for normal shaded verification.
- Use `wireframe` or `section` when internal geometry or edge flow matters.
- Use `capture gif` or `capture mp4` for motion and presentation.

## Export

```bash
forgecad export stl path/to/model.forge.js
forgecad export 3mf path/to/model.forge.js --quality high
forgecad export step path/to/model.forge.js
forgecad export report path/to/model.forge.js out/report.pdf
forgecad export cutting-layout path/to/sheet-stock-model.forge.js --sheet-width 420 --sheet-height 594 --kerf 3
```

Pick the export that matches the goal: mesh for printing, STEP for exact CAD interchange, report for review, cutting layout for sheet-stock workflows.


---

<!-- API/core/concepts.md -->

# ForgeCAD Core Concepts

ForgeCAD scripts are JavaScript that returns geometry. The forge API is globally available — no imports needed.

```javascript
const width = param("Width", 50, { min: 20, max: 100, unit: "mm" });
return box(width, 30, 10);
```

## Injected Runtime Names

ForgeCAD API functions and classes are injected into every `.forge.js` script. Use them directly; do not import or destructure ForgeCAD API names from helper files.

```javascript
// BAD — `bom` and `bomToCsv` are already built-in runtime names.
const { bom, bomToCsv } = require("./bom.js");

// GOOD — use the built-in directly.
bom(4, "M4 bolt");

// GOOD — keep project helpers under their own local name.
const bomHelpers = require("./bom.js");
bomHelpers.addFasteners(...);
```

Top-level declarations such as `const bom = ...`, `let scene = ...`, or `class Shape {}` collide with the injected runtime names. If you need a local helper, choose a project-specific name like `projectBom`, `sceneConfig`, or `makeShape`.

## Execution Model

- Scripts re-execute on every parameter change (400ms debounce)
- Geometry operations are **immutable** — shapes, sketches, groups, imported assemblies, and wood boards return new values instead of modifying in place
- Must return one of: `Shape`, `Sketch`, `ShapeGroup`, `Assembly`, `SolvedAssembly`, `SdfShape`, `Array` of renderables, `Array` of `{ name, tags?, shape?, sketch?, group?, color? }`, or a **metadata object** (see below)

Top-level assembly scripts can return an unsolved `Assembly` directly; ForgeCAD solves it at default joint values for display. Return `assembly.solve(state)` when you want a specific pose. Do not call `.toGroup()` just to make an assembly render — use `.toGroup()` only when you specifically need `ShapeGroup` composition, group-style transforms, or named-child lookup.

### Metadata Object Return

A script can return a plain object whose values include renderable geometry alongside non-renderable metadata. All renderable entries (Shape, Sketch, ShapeGroup, Assembly, SolvedAssembly, SdfShape, or Array of named objects) are rendered; non-renderable entries are silently skipped. This is useful for multi-file projects where a part needs to publish interface data (bolt positions, dimensions) to other files:

When importing project files, include the full extension in every relative path: `require('./motor-mount.forge.js')` for model files and `require('./helpers.js')` for plain helper modules. ForgeCAD resolves project imports by exact path and does not infer `.forge.js` or `.js` from `require('./motor-mount')`.

```javascript
// motor-mount.forge.js — renders standalone, exports metadata via require()
const holePositions = [[17, 15], [-29, 15], [17, -15], [-29, -15]];
return {
  shape: mount.color('#556B2F'),                        // rendered
  bolts: { dia: 5.3, pos: holePositions },              // metadata — skipped in render, available via require()
};

// base-body.forge.js — imports mount, accesses .bolts
const mount = require('./motor-mount.forge.js');
for (const [x, y] of mount.bolts.pos) { ... }          // use metadata
// mount.shape is the Shape if you need it in an assembly
```

Arrays inside the object are also rendered:

```javascript
return {
  parts: [{ name: 'Left', shape: leftShape }, { name: 'Right', shape: rightShape }],
  armWidth: 6,  // metadata
};
```

Named return objects and named `group(...)` children can include `tags`. Tags are viewport metadata: they do not affect geometry, exports, face labels, or BOM rows, but the command palette can hide, show only, or focus every object with a selected tag.

```javascript
return [
  { name: 'Base Plate', tags: ['printed', 'structural'], shape: base },
  { name: 'M4 Bolt A', tags: 'fastener', shape: boltA },
  { name: 'M4 Bolt B', tags: 'fastener', shape: boltB },
];
```

## Coordinate System

Z-up right-handed: X = left/right, Y = forward/back, Z = up/down.

## Colors

`.color(hex)` works on `Shape` and `Sketch`. Colors survive transforms. Boolean operations return a single result shape, so only the first operand's color survives.

**`union()` merges shapes into one solid mesh** — later operands do not keep separate colors or identities. Use `group(...)` or return named objects instead when you want separate parts:

```javascript
return [
  { name: "Base", shape: box(100, 100, 5), color: "#888888" },
  { name: "Column", shape: cylinder(50, 10).translate(50, 50, 5), color: "#4488cc" },
];
```

## Face Operations

Shapes carry semantic face labels through their lifecycle. The flow is:

1. **Primitives** assign canonical names — `box()` gives you `top`, `bottom`, `side-left`, etc.; `cylinder()` gives `top`, `bottom`, `side`.
2. **Extrusions** inherit labels from the sketch and add `top`/`bottom`.
3. **Transforms** (translate, rotate, scale, mirror) preserve all labels.
4. **Booleans** preserve labels from the first operand where geometry survives.

You resolve labels to geometry with `.face(name)` or `.face(query)` — see the Shape class docs for the full query API. Operations like `.pocket()`, `.boss()`, `.hole()`, and `faceProfile()` all consume face references.

## Text vs Viewport Labels

Default to no explanatory text inside CAD geometry. A ForgeCAD model should represent the physical artifact, not a labeled teaching diagram. Explain the design through file names, named return objects, comments, BOM entries, inspection bundles, and companion docs.

Use `text2d()` only when the letters are part of the real object: raised branding, engraving, serial plates, keyboard legends, gauge ticks, connector labels, service arrows, scale markings, or exported manufacturing markings. `text2d()` builds filled sketch geometry from font outlines, so it can make exact/OCCT workflows slower.

Use `Viewport.label(text, [x, y, z], options)` only for temporary review, debug, tutorial, or explicitly requested presentation views. Render labels are annotations only: they do not create meshes, do not export, do not enter the B-rep path, and do not add face labels. Do not use viewport labels to compensate for unclear geometry in the final model.

## SDF Modeling

For organic shapes, smooth blending, TPMS lattices, and surface deformations. Return `SdfShape` values directly, or return a plain object/array tree of SDF leaves, for native raymarch preview. Use `.toShape()` or `toShape(...)` only when you need mesh-backed CAD/export behavior. See [sdf-primitives.md](sdf-primitives.md).

---

<!-- generated/core.md -->

# Core API

3D primitives, boolean operations, transforms, patterns, imports, and parameters.

## Contents

- [3D Primitives](#3d-primitives) — `box`, `cylinder`, `sphere`, `torus`
- [Boolean Operations](#boolean-operations) — `union`, `difference`, `intersection`
- [Edge Features](#edge-features) — `fillet`, `chamfer`, `draft`, `offsetSolid`
- [Patterns & Layout](#patterns-layout) — `circularLayout`, `polygonVertices`, `linearPattern`, `circularPattern`, `linearPattern2d`, `circularPattern2d`, `mirrorCopy`, `selectEdges`, `selectEdge`, `coalesceEdges`
- [Imports & Composition](#imports-composition) — `require`, `importSvgSketch`, `importMesh`, `importStep`
- [Parameters](#parameters) — `Param.number`, `Param.string`, `Param.bool`, `Param.choice`, `Param.list`
- [Grouping & Local Coordinates](#grouping-local-coordinates) — `group`
- [Section & Projection](#section-projection) — `intersectWithPlane`, `faceProfile`, `projectToPlane`
- [Transforms](#transforms) — `composeChain`
- [Verification](#verification) — `verify.that`, `verify.equal`, `verify.notEqual`, `verify.greaterThan`, `verify.lessThan`, `verify.inRange`, `verify.centersCoincide`, `verify.connectorDistance`, `verify.physicalComponentCount`, `verify.intentionalOverlap`, `verify.notColliding`, `verify.minClearance`, `verify.clearanceBetween`, `verify.parallel`, `verify.perpendicular`, `verify.coplanar`, `verify.faceAt`, `verify.sameDirection`, `verify.isEmpty`, `verify.notEmpty`, `verify.volumeApprox`, `verify.areaApprox`, `verify.boundingBoxSize`, `verify.edgeContinuity`, `verify.noTinyEdges`, `verify.noSliverFaces`, `verify.noSelfIntersection`, `spec`
- [Shape](#shape) — Appearance, Face Topology, Edge Topology, Transforms, Booleans & Cutting, Features, Placement, Connectors, References, Measurement
- [Transform](#transform)
- [ShapeGroup](#shapegroup) — Children, Transforms, Placement, Connectors, References
- [SurfacePattern](#surfacepattern)
- [Pattern2D](#pattern2d)
- [Pattern2DBuilder](#pattern2dbuilder)
- [ShapeRef](#shaperef)
- [ANCHOR3D_NAMES](#anchor3d-names)
- [verify](#verify)
- [Constraint](#constraint)
- [Points](#points)
- [connector](#connector)

## Functions

### 3D Primitives

#### `box()` — Create a rectangular box. Centered on XY, base at Z=0.

Extents:

- X: `[-width/2, width/2]`
- Y: `[-depth/2, depth/2]`
- Z: `[0, height]`

For named faces, build from a labeled sketch: `rect(width, depth).labelEdges('s', 'e', 'n', 'w').extrude(height, { labels: { start: 'bottom', end: 'top' } })`.

```ts
box(width: number, depth: number, height: number): Shape
```

#### `cylinder()` — Create a cylinder or cone with named faces and edges. Centered on XY, base at Z=0.

Extents:

- X/Y: centered at the origin
- Z: `[0, height]`

`radiusTop` defaults to `radius`. Set `radiusTop` smaller to taper the side, or `0` for a pointy cone. Use `segments` to create regular prisms (for example `6` for a hexagonal prism).

Named faces: `top`, `bottom`, `side` Named edges: `top-rim`, `bottom-rim`

```ts
cylinder(height: number, radius: number, radiusTop?: number, segments?: number): Shape
```

#### `sphere()` — Create a sphere centered at the origin.

Extents:

- X: `[-radius, radius]`
- Y: `[-radius, radius]`
- Z: `[-radius, radius]`

Use `segments` for lower-poly approximations.

```ts
sphere(radius: number, segments?: number): Shape
```

#### `torus()` — Create a torus (donut shape) lying in the XY plane. Centered on all axes.

Extents:

- X: `[-(majorRadius + minorRadius), +(majorRadius + minorRadius)]`
- Y: `[-(majorRadius + minorRadius), +(majorRadius + minorRadius)]`
- Z: `[-minorRadius, minorRadius]`

The origin is the center of the ring.

```ts
torus(majorRadius: number, minorRadius: number, segments?: number): Shape
```

### Boolean Operations

#### `union()` — Combine shapes into a single solid (additive boolean).

Accepts individual shapes, or an array of shapes. `union()` returns one solid, so only the first operand's color is preserved in the result. Use `group()` when you want separate child colors or identities.

```ts
union(...inputs: ShapeOperandInput[]): Shape
```

#### `difference()` — Subtract shapes from a base shape (subtractive boolean).

The first shape is the base; all subsequent shapes are subtracted from it. Accepts individual shapes, or an array of shapes.

```ts
difference(...inputs: ShapeOperandInput[]): Shape
```

#### `intersection()` — Keep only the overlapping volume of the input shapes (intersection boolean).

Requires at least two shapes. Accepts individual shapes, or an array.

```ts
intersection(...inputs: ShapeOperandInput[]): Shape
```

### Edge Features

#### `fillet()` — Apply experimental fillets (rounded edges) to one or more edges of a shape.

**Experimental**: fillets are still backend-sensitive. The Manifold backend is known to produce incorrect results for some edge-finish cases, and the OCCT backend can be very slow, especially with broad edge selections. Prefer targeted edge selectors and inspect the result before treating it as production-ready geometry.

Edge selections compile into backend operations; unsupported selections fail as explicit kernel gaps instead of using TypeScript geometry fallbacks.

The `edges` parameter is flexible:

- Omit to fillet **all** sharp edges
- Pass an `EdgeQuery` for an inline filter (most common)
- Pass an `EdgeSegment` or `EdgeSegment[]` from `selectEdges()` for pre-selected edges

Throws if no edges match the selection, or if `radius` is not a positive finite number.

```ts
// Fillet all edges
fillet(myShape, 2)

// Fillet only top convex edges
fillet(myShape, 1.5, { atZ: 20, convex: true })

// Fillet vertical edges selected beforehand
const edges = selectEdges(myShape, { parallel: [0, 0, 1] })
fillet(myShape, 3, edges)
```

```ts
fillet(shape: Shape, radius: number, edges?: EdgeSelector, segments?: number): Shape
```

#### `chamfer()` — Apply experimental chamfers (beveled edges) to one or more edges of a shape.

**Experimental**: chamfers are still backend-sensitive. The Manifold backend is known to produce incorrect results for some edge-finish cases, and the OCCT backend can be very slow, especially with broad edge selections. Prefer targeted edge selectors and inspect the result before treating it as production-ready geometry.

Produces a 45° bevel at the specified `size` (distance from edge). Edge selections compile into backend operations; unsupported selections fail as explicit kernel gaps instead of using TypeScript geometry fallbacks.

The `edges` parameter accepts the same options as `fillet()`: inline `EdgeQuery`, pre-selected `EdgeSegment`/`EdgeSegment[]`, or `undefined` (all sharp edges).

```ts
// Chamfer all edges
chamfer(myShape, 1)

// Chamfer only vertical edges
chamfer(myShape, 2, { parallel: [0, 0, 1] })
```

```ts
chamfer(shape: Shape, size: number, edges?: EdgeSelector): Shape
```

#### `draft()` — Apply a draft angle (taper) to vertical faces for mold extraction.

Adds a taper angle to the vertical faces of a solid so that it can be extracted from a mold. The neutral plane is the Z position where the draft angle is zero — faces above and below are tapered symmetrically. Typical values for injection molding are 1–5°.

Truck supports vertical-prism solids with Z-axis pull directions. OCCT uses its native draft operation when available. Manifold throws.

```ts
// Add 3° draft to a box for injection molding
draft(myBox, 3)

// Draft with custom pull direction and neutral plane
draft(myShape, 2, [0, 0, 1], 10)
```

```ts
draft(shape: Shape, angleDeg: number, pullDirection?: [ number, number, number ], neutralPlaneOffset?: number): Shape
```

#### `offsetSolid()` — Uniformly offset all surfaces of a solid inward or outward.

Unlike `shell()`, which hollows a solid by removing one face, `offsetSolid()` produces a new solid whose every surface is shifted by `thickness`. Positive values grow the shape outward; negative values shrink it inward.

Requires the OCCT backend. Throws on Manifold.

```ts
// Grow a box outward by 1mm on all sides
offsetSolid(myBox, 1)

// Shrink a shape inward by 0.5mm
offsetSolid(myShape, -0.5)
```

```ts
offsetSolid(shape: Shape, thickness: number): Shape
```

### Patterns & Layout

#### `circularLayout()` — Compute evenly-spaced positions around a circle.

Eliminates the most common trig pattern in CAD scripts:

```js
// Before — manual trig
for (let i = 0; i < 12; i++) {
  const angle = i * 30 * Math.PI / 180;
  markers.push(marker.translate(r * Math.cos(angle), r * Math.sin(angle), 0));
}

// After — declarative
for (const {x, y} of circularLayout(12, r)) {
  markers.push(marker.translate(x, y, 0));
}
```

```ts
circularLayout(count: number, radius: number, options?: CircularLayoutOptions): LayoutPoint[]
```

**`CircularLayoutOptions`**
- `startDeg?: number` — Angle of the first element in degrees (default: 0 = +X axis).
- `centerX?: number` — Center X coordinate (default: 0).
- `centerY?: number` — Center Y coordinate (default: 0).

`LayoutPoint`: `{ x: number, y: number }`

#### `polygonVertices()` — Compute the vertex positions of a regular polygon.

Default orientation places the first vertex at the top (90 degrees), matching the convention used by [`ngon()`](/docs/sketch#ngon).

Eliminates manual Math.sqrt(3) for triangles, pentagon vertex math, etc:

```js
// Before — manual equilateral triangle
const v1 = [center.x - r/2, center.y + r * Math.sqrt(3)/2];
const v2 = [center.x - r/2, center.y - r * Math.sqrt(3)/2];
const v3 = [center.x + r, center.y];

// After — declarative
const [v1, v2, v3] = polygonVertices(3, r);
```

```ts
polygonVertices(sides: number, radius: number, options?: PolygonVerticesOptions): LayoutPoint[]
```

**`PolygonVerticesOptions`**
- `startDeg?: number` — Angle of the first vertex in degrees (default: 90 = top).
- `centerX?: number` — Center X coordinate (default: 0).
- `centerY?: number` — Center Y coordinate (default: 0).

#### `linearPattern()` — Repeat a shape in a linear pattern along a direction vector and union the copies.

Creates `count` copies of `shape`, each offset by `(dx*i, dy*i, dz*i)` from the original. All copies are unioned into a single `Shape`. Distinct compiler ownership is assigned to each copy so face identity via owner-scoped canonical queries still works post-merge.

```ts
// 5 cylinders, 20mm apart along X
linearPattern(cylinder(10, 3), 5, 20, 0)
```

```ts
linearPattern(shape: Shape, count: number, dx: number, dy: number, dz?: number): Shape
```

#### `circularPattern()` — Repeat a shape in a circular pattern around an axis and union the copies.

Distributes `count` copies evenly around the rotation axis (360° / count per step). All copies are unioned into a single `Shape`. Distinct compiler ownership is assigned to each copy — post-merge face identity via owner-scoped canonical queries still works for pattern descendants.

Two calling conventions:

- **Simple** (Z axis): `circularPattern(shape, 6)` or `circularPattern(shape, 6, centerX, centerY)`
- **Advanced** (arbitrary axis): `circularPattern(shape, 6, { axis, origin })`

```ts
// 8 holes evenly spaced around origin
circularPattern(cylinder(12, 4).translate(30, 0, -1), 8)

// Circular pattern around X axis
circularPattern(myFeature, 4, { axis: [1, 0, 0], origin: [0, 0, 50] })
```

```ts
circularPattern(shape: Shape, count: number, centerXOrOpts?: number | CircularPatternOptions, centerY?: number): Shape
```

**`CircularPatternOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `centerX?` | `number` | Center X of the rotation (default: 0). Used when axis is Z (legacy mode). |
| `centerY?` | `number` | Center Y of the rotation (default: 0). Used when axis is Z (legacy mode). |
| `axis?` | `[ number, number, number ]` | Rotation axis direction (default: [0, 0, 1] = Z axis). |
| `origin?` | `[ number, number, number ]` | Pivot point for the rotation (default: [0, 0, 0]). Overrides centerX/centerY when set. |

#### `linearPattern2d()` — Repeat a 2D sketch in a linear pattern and union the copies.

```ts
linearPattern2d(sketch: Sketch, count: number, dx: number, dy?: number): Sketch
```

#### `circularPattern2d()` — Repeat a 2D sketch in a circular pattern around a center point and union the copies.

```ts
circularPattern2d(sketch: Sketch, count: number, centerXOrOpts?: number | { centerX?: number; centerY?: number; startDeg?: number; }, centerY?: number): Sketch
```

#### `mirrorCopy()` — Mirror a shape across a plane and union the mirror with the original.

The mirror plane passes through the origin and is defined by its normal vector. The mirrored copy is unioned with the original to produce a single symmetric Shape.

```ts
// Mirror across the YZ plane (X=0)
mirrorCopy(box(50, 30, 10), [1, 0, 0])
```

```ts
mirrorCopy(shape: Shape, normal: [ number, number, number ]): Shape
```

#### `selectEdges()` — Select all edges from a shape that match the given query.

Uses the active kernel's native topology query when available (Truck), otherwise extracts sharp edges from the mesh (dihedral angle > 1°), applies all filters in the query, and returns the matching `EdgeSegment[]`. When `near` is specified the results are sorted closest-first.

Works on any shape — primitives, booleans, shells, and imported meshes. Use this when tracked topology is unavailable (e.g. after a difference or on imported geometry). For simpler cases, pass an `EdgeQuery` directly to `fillet()` or `chamfer()` instead of calling `selectEdges` separately.

```ts
// Fillet all top edges of a box
const topEdges = selectEdges(part, { atZ: 20, perpendicular: [0, 0, 1] });
let result = part;
for (const edge of coalesceEdges(topEdges)) {
  result = fillet(result, 2, edge);
}
```

```ts
selectEdges(shape: Shape, query?: EdgeQuery): EdgeSegment[]
```

**`EdgeQuery`**

| Option | Type | Description |
|--------|------|-------------|
| `near?` | `Vec3` | Sort by proximity to this point (closest first). When used with `selectEdge`, picks the closest match. |
| `parallel?` | `Vec3` | Filter: edge direction approximately parallel to this vector. |
| `perpendicular?` | `Vec3` | Filter: edge direction approximately perpendicular to this vector. |
| `convex?` | `boolean` | Filter: only convex (outside corner) edges. |
| `concave?` | `boolean` | Filter: only concave (inside corner) edges. |
| `minAngle?` | `number` | Filter: minimum dihedral angle in degrees. |
| `maxAngle?` | `number` | Filter: maximum dihedral angle in degrees. |
| `minLength?` | `number` | Filter: minimum edge length. |
| `maxLength?` | `number` | Filter: maximum edge length. |
| `within?` | `BoundingRegion` | Filter: edge midpoint must be within this bounding region. |
| `atZ?` | `number` | Shorthand: edge midpoint Z ≈ this value (within `tolerance`). Equivalent to `within: { zMin: atZ - tol, zMax: atZ + tol }`. |
| `tolerance?` | `number` | Position tolerance for approximate matches (default: `1.0`). Used by `atZ` and `near`. |
| `angleTolerance?` | `number` | Angular tolerance in degrees for `parallel`/`perpendicular` filters (default: `10`). |

`BoundingRegion`: `{ xMin?: number, xMax?: number, yMin?: number, yMax?: number, zMin?: number, zMax?: number }`

**`EdgeSegment`**

| Option | Type | Description |
|--------|------|-------------|
| `index` | `number` | Stable index within the extraction (deterministic for a given mesh). |
| `direction` | `Vec3` | Normalized direction from start → end. |
| `dihedralAngle` | `number` | Dihedral angle in degrees (0 = coplanar, 180 = knife edge). |
| `convex` | `boolean` | true = outside corner (convex), false = inside corner (concave). |
| `normalA` | `Vec3` | Normal of first adjacent face. |
| `normalB` | `Vec3` | Normal of second adjacent face (same as normalA for boundary edges). |
| `boundary` | `boolean` | true if this is a boundary (unmatched) edge — unusual for closed solids. |
| `start`, `end`, `midpoint`, `length` | | — |

#### `selectEdge()` — Select the single best-matching edge from a shape.

When `near` is specified, returns the edge whose midpoint is closest to that point. Otherwise returns the first matching edge in mesh order. Throws if no edges match the query — useful as a guard when you expect exactly one result.

```ts
// Chamfer one specific edge near a known point
const bottomEdge = selectEdge(part, { near: [25, 0, 0], atZ: 0 });
result = chamfer(result, 1.5, bottomEdge);
```

```ts
selectEdge(shape: Shape, query?: EdgeQuery): EdgeSegment
```

#### `coalesceEdges()` — Merge collinear edge segments into longer logical edges.

Tessellation often splits one geometric edge into multiple short segments. `coalesceEdges` groups adjacent collinear segments and merges each group into a single `EdgeSegment` spanning the full extent. This is usually needed before passing edges to `fillet()` or `chamfer()` on non-primitive shapes.

The `tolerance` controls the maximum perpendicular distance from collinearity before two segments are considered non-collinear. Default: `0.01`.

```ts
const topEdges = selectEdges(part, { atZ: 20 });
for (const edge of coalesceEdges(topEdges)) {
  result = fillet(result, 2, edge);
}
```

```ts
coalesceEdges(segments: EdgeSegment[], tolerance?: number): EdgeSegment[]
```

### Imports & Composition

#### `require()` — Import a module with optional ForgeCAD parameter overrides. Returns the module's exports.

When importing a `.forge.js` file, the return value is what the script returns. If the script returns a metadata object (e.g. `{ shape: myShape, bolts: {...} }`), the caller receives the full object — renderable values and metadata together.

**Path rule:** Always include the file extension in relative imports: use `require("./part.forge.js")` for model files and `require("./helpers.js")` for plain helper modules. ForgeCAD does not apply Node-style extension inference, so `require("./part")` will not find `part.forge.js` or `part.js`.

**Parameter scoping:** Parameters declared in required files are automatically namespaced with a `"filename#N / "` prefix (e.g. `"bracket.forge.js#1 / Width"`). This prevents collisions when multiple files declare same-named params. Each file's params appear as separate sliders.

**Parameter overrides:** When passing overrides, use the bare param name (not the scoped name). Overrides are type-checked — unrecognized keys throw an error with typo suggestions.

**Multi-file assembly pattern** — pass cross-cutting design values from the assembly to parts:

```js
// assembly.forge.js — owns cross-cutting params, passes to parts
const wall = param("Wall", 3);
const baseH = param("Base Height", 20);

const mount = require('./motor-mount.forge.js', { Wall: wall });
const base  = require('./base-body.forge.js', { Wall: wall, Height: baseH });
```

**Metadata pattern** — parts publish interface data alongside geometry:

```js
// motor-mount.forge.js
return { shape: mount, bolts: { dia: 5.3, pos: holePositions } };

// base-body.forge.js
const mount = require('./motor-mount.forge.js');
mount.bolts.pos  // access the metadata
mount.shape       // access the geometry
```

```ts
require(path: string, paramOverrides?: Record<string, number | string>): any
```

#### `importSvgSketch()` — Parse an SVG file and return it as a Sketch with options for region filtering, scaling, and simplification.

```ts
importSvgSketch(fileName: string, options?: SvgImportOptions): Sketch
```

**`SvgImportOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `include?` | `"auto" \| "fill" \| "stroke" \| "fill-and-stroke"` | Which geometry channels to include: - `auto`: prefer fills; if no fill geometry exists, fall back to strokes - `fill`: import only filled regions - `stroke`: import only stroke geometry - `fill-and-stroke`: include both |
| `regionSelection?` | `"all" \| "largest"` | Keep all disconnected regions, or only the largest. |
| `maxRegions?` | `number` | Keep at most this many regions (largest-first). |
| `minRegionArea?` | `number` | Drop regions below this absolute area threshold. |
| `minRegionAreaRatio?` | `number` | Drop regions below this ratio of largest-region area. |
| `flattenTolerance?` | `number` | Curve flattening tolerance in SVG user units. Smaller = more segments, higher fidelity. |
| `arcSegments?` | `number` | Minimum segment count for arc discretization. |
| `scale?` | `number` | Global scale applied after SVG parsing. |
| `maxWidth?` | `number` | Maximum imported sketch width. If exceeded, geometry is uniformly downscaled to fit. |
| `maxHeight?` | `number` | Maximum imported sketch height. If exceeded, geometry is uniformly downscaled to fit. |
| `centerOnOrigin?` | `boolean` | Recenter imported geometry so its 2D bounds center is at CAD origin. |
| `simplify?` | `number` | Simplification tolerance for final sketch cleanup. |
| `invertY?` | `boolean` | Flip SVG Y-down coordinates to CAD Y-up. Enabled by default. |

#### `importMesh()` — Import an external mesh file (STL, OBJ, 3MF) as a Shape.

```ts
importMesh(fileName: string, options?: { scale?: number; center?: boolean; }): Shape
```

#### `importStep()` — Import a STEP file (.step, .stp) as an exact OCCT-backed Shape. Preserves NURBS curves, B-spline surfaces, and exact topology. Requires running with the OCCT backend.

```ts
importStep(fileName: string): Shape
```

### Parameters

#### `Param.number()` — Declare a numeric parameter that renders as a slider in the UI.

Each call registers a slider control. When the user moves the slider the entire script re-executes with the new value. Parameter values are also overridable from `require()` imports or the CLI `--param` flag — the `name` string is the key used in both cases.

Default range rules when options are omitted:

- `min` defaults to `0`
- `max` defaults to `defaultValue * 4`
- `step` is auto-calculated: `1` for integer params, `0.1` for ranges ≤ 100, `1` for larger ranges

The `unit` option is cosmetic only — no conversion is performed. Use `integer: true` for counts, sides, quantities (rounds to whole numbers; step defaults to `1`).

```ts
const width = Param.number("Width", 50);
const angle = Param.number("Angle", 45, { min: 0, max: 180, unit: "°" });
const sides = Param.number("Sides", 6, { min: 3, max: 12, integer: true });
```

**Parameter overrides** — key must match `name` exactly:

```ts
// Via require()
const bracket = require("./bracket.forge.js", { Width: 80 });

// Via CLI
// forgecad run model.forge.js --param "Wall Thickness=3"
```

Also available as the shorthand alias `param()`.

```ts
Param.number(name: string, defaultValue: number, opts?: { min?: number; max?: number; step?: number; unit?: string; integer?: boolean; reverse?: boolean; }): number
```

#### `Param.string()` — Declare a string parameter that renders as a text input in the UI.

String parameters let users type free-form text — labels, names, inscriptions, file paths, etc. The `name` string is the override key.

```ts
const label = Param.string("Label", "Hello World");
const name  = Param.string("Name", "Part-001", { maxLength: 20 });
```

Override via import:

```ts
const tag = require("./tag.forge.js", { Label: "Custom Text" });
```

Only available as `Param.string()` — no standalone alias.

```ts
Param.string(name: string, defaultValue: string, opts?: { maxLength?: number; }): string
```

#### `Param.bool()` — Declare a boolean parameter that renders as a checkbox in the UI.

Internally stored as `0`/`1`. When overriding from CLI or `require()`, pass `1` for true and `0` for false. The `name` string is the override key.

```ts
const showHoles = Param.bool("Show Holes", true);
if (showHoles) return difference(plate, cylinder(10, 5).translate(50, 30, 0));
return plate;
```

Override via import:

```ts
const pan = require("./pan.forge.js", { "Show Lid": 0 });
```

Also available as the shorthand alias `boolParam()`.

```ts
Param.bool(name: string, defaultValue: boolean): boolean
```

#### `Param.choice()` — Declare a choice parameter that renders as a dropdown in the UI.

`defaultValue` must exactly match one entry in `choices`. Returns the selected string label. Prefer `Param.choice` over `Param.number` when a slider would hide intent — named choices like `"wok"` are self-describing.

Overrides may be passed as the choice label string (preferred) or as a numeric index. The `name` string is the override key.

```ts
const panStyle = Param.choice("Pan Style", "frying-pan", ["frying-pan", "saute-pan", "wok"]);
if (panStyle === "wok") return buildWok();
```

Override via import:

```ts
const pan = require("./pan.forge.js", { "Pan Style": "wok" });
```

Override via CLI:

```bash
forgecad run model.forge.js --param "Pan Style=wok"
```

Also available as the shorthand alias `choiceParam()`.

```ts
Param.choice(name: string, defaultValue: string, choices: string[]): string
```

#### `Param.list()` — Declare a list parameter — an array of struct items with per-field UI controls.

Each item in the list is a struct whose fields each render as their own control (slider, checkbox, or dropdown). The user can add/remove rows up to `minItems`/`maxItems` bounds.

Field types:

- Boolean fields (`boolean: true` in field defs) return as `boolean`
- Choice fields (`choices: [...]` in field defs) return as `string`
- All other fields return as `number`

```ts
Param.list<T extends Record<string, number | boolean | string>>(name: string, defaultItems: T[], opts: { ... }): T[]
```

`ListParamFieldDef`: `{ min?: number, max?: number, step?: number, unit?: string, integer?: boolean, boolean?: boolean, choices?: string[] }`

### Grouping & Local Coordinates

#### `group()` — Group multiple shapes/sketches for joint transforms without merging into a single mesh.

Unlike union(), child colors and individual identities are preserved. Children can be plain shapes, named descriptors ({ name, shape/sketch/group }), or nested groups. The returned ShapeGroup supports all Shape transforms (translate, rotate, etc.).

Named descriptors can include `tags` for viewport organization. Tags do not affect geometry; they let the command palette hide, show only, or focus all objects with the same tag.

**Local coordinate pattern:** Build child parts at the origin (local coordinates), then group and translate once to place the whole assembly. This eliminates the error-prone pattern of manually adding parent offsets to every sub-part.

```js
const body = roundedBox(100, 20, 32, 4);
const panel = box(98, 2, 18).translate(0, -12, 4);
const louver = box(88, 2, 6).translate(0, -14, -11);
const indoorUnit = group(
  { name: 'Body', shape: body },
  { name: 'Panel', tags: 'cover', shape: panel },
  { name: 'Louver', tags: ['cover', 'moving'], shape: louver },
).translate(0, -18, 70);
```

```ts
group(...items: GroupInput[]): ShapeGroup
```

### Section & Projection

#### `intersectWithPlane()` — Cross-section: slice a 3D shape with a plane and return the intersection as a 2D Sketch.

```ts
intersectWithPlane(shape: Shape, plane: PlaneSpec): Sketch
```

#### `faceProfile()` — Extract the boundary profile of a named face as a 2D sketch.

The result is returned in the face's local 2D coordinate system, making it convenient for offsets, pocket profiles, or follow-up sketch operations driven by an existing face.

```ts
faceProfile(shape: Shape, face: FaceSelector): Sketch
```

#### `projectToPlane()` — Orthographically project a 3D shape onto a plane and return the silhouette as a 2D Sketch.

```ts
projectToPlane(shape: Shape, plane: PlaneSpec): Sketch
```

### Transforms

#### `composeChain()` — Compose transforms in chain order. Equivalent to Transform.identity().mul(a).mul(b).mul(c)...

```ts
composeChain(...steps: TransformInput[]): Transform
```

### Verification

#### `verify.that()` — Custom predicate check.

```ts
verify.that(label: string, check: () => boolean, message?: string): void
```

#### `verify.equal()` — Check that two numbers are approximately equal (within tolerance).

```ts
verify.equal(label: string, actual: number, expected: number, tolerance?: number, message?: string): void
```

#### `verify.notEqual()` — Check that two numbers are NOT equal (differ by more than tolerance).

```ts
verify.notEqual(label: string, actual: number, unexpected: number, tolerance?: number, message?: string): void
```

#### `verify.greaterThan()` — Check that actual > min.

```ts
verify.greaterThan(label: string, actual: number, min: number, message?: string): void
```

#### `verify.lessThan()` — Check that actual < max.

```ts
verify.lessThan(label: string, actual: number, max: number, message?: string): void
```

#### `verify.inRange()` — Check that min <= actual <= max.

```ts
verify.inRange(label: string, actual: number, min: number, max: number, message?: string): void
```

#### `verify.centersCoincide()` — Check that the bounding-box centers of two shapes coincide within tolerance (mm).

```ts
verify.centersCoincide(label: string, a: ShapeLike, b: ShapeLike, tolerance?: number): void
```

`ShapeLike`: `{ min: number[], max: number[] }`

#### `verify.connectorDistance()` — Check the distance between two named connectors on a shape or group.

Use this when connectors + `matchTo()` define a static assembly interface. It proves the mate at runtime, unlike a plain source-level connector declaration. The common case is `expected = 0`, meaning the two connector origins should coincide after placement.

```ts
verify.connectorDistance("leg is seated", bench, "Rail.leg_0", "Leg0.head", 0, 0.01);
```

```ts
verify.connectorDistance(label: string, target: ConnectorDistanceLike, connectorA: string, connectorB: string, expected?: number, tolerance?: number): void
```

#### `verify.physicalComponentCount()` — Declare the expected physical connectivity component count for the returned visible model.

Use this for generated mechanical models that should have a clear component graph: one connected fixture, a purchased part plus a removable cartridge, a root assembly plus named intentional ghosts, and so on. `forgecad inspect mechanical-integrity` resolves the returned visible objects with the same physical-connectivity analysis used in the quality gate and fails if the actual component count differs.

This catches the common generated-CAD failure where a script returns a visually plausible artifact but the handle, screw, washer, cover, or terminal block is actually a separate island.

```ts
verify.physicalComponentCount("vise is one connected installed assembly", 1);
```

```ts
verify.physicalComponentCount(label: string, expected: number): void
```

#### `verify.intentionalOverlap()` — Declare that two visible objects intentionally overlap because the overlap is real manufacturing intent.

Use this only for overlaps that a mechanical reviewer would accept as actual matter sharing volume: welded/fused regions, overmolded inserts, potted electronics, cast-in hardware, or deliberately bonded laminations. This is not a shortcut for screws without holes, shafts without bores, covers without pockets, or parts placed with collision as a positioning hack.

`forgecad inspect mechanical-integrity --collisions` only honors this declaration when both shapes are returned as visible objects and the exact collision report finds that same object pair. Unused or non-visible declarations fail the quality gate so annotations cannot hide unrelated collisions.

```ts
verify.intentionalOverlap("rubber grip is overmolded on handle", rubberGrip, handleCore, "overmolded insert");
```

```ts
verify.intentionalOverlap(label: string, a: ShapeLike, b: ShapeLike, reason: string): void
```

#### `verify.notColliding()` — Check that two shapes do not collide (minGap > 0).

```ts
verify.notColliding(label: string, a: ShapeLike, b: ShapeLike, searchLength?: number): void
```

#### `verify.minClearance()` — Check that a minimum clearance gap exists between two shapes.

```ts
verify.minClearance(label: string, a: ShapeLike, b: ShapeLike, minGap: number, searchLength?: number): void
```

#### `verify.clearanceBetween()` — Check that the clearance gap between two shapes is inside an allowed range.

Use this for seated and retained interfaces where a part must be close enough to be mechanically accountable, but must not collide beyond the allowed minimum. It catches both failure modes that make generated CAD look fake: parts floating away from their receiver, and parts intersecting their receiver because the pocket, bore, or running clearance was not modeled.

For contact, use a narrow range such as `[-0.01, 0.05]` to tolerate tiny numerical noise. For a running fit, use the intended clearance band.

Manifold-backed shapes use exact min-gap distance. Other backends use a mesh-derived min-gap check and say so in the verification message; keep `forgecad inspect mechanical-integrity --collisions` in the acceptance gate for positive-volume interference.

```ts
verify.clearanceBetween("cover is seated on gasket", cover, gasket, -0.01, 0.05);
verify.clearanceBetween("carriage runs inside rail", carriage, rail, 0.2, 0.5);
```

```ts
verify.clearanceBetween(label: string, a: ShapeLike, b: ShapeLike, minGap: number, maxGap: number, searchLength?: number): void
```

#### `verify.parallel()` — Check that two face normals are parallel (within toleranceDeg degrees).

```ts
verify.parallel(label: string, faceA: FaceRefLike, faceB: FaceRefLike, toleranceDeg?: number): void
```

`FaceRefLike`: `{ normal: [ number, number, number ], center: [ number, number, number ] }`

#### `verify.perpendicular()` — Check that two face normals are perpendicular (within toleranceDeg degrees).

```ts
verify.perpendicular(label: string, faceA: FaceRefLike, faceB: FaceRefLike, toleranceDeg?: number): void
```

#### `verify.coplanar()` — Check that a face is coplanar with (same plane as) another face, meaning they are parallel AND their centers lie on the same plane.

```ts
verify.coplanar(label: string, faceA: FaceRefLike, faceB: FaceRefLike, toleranceDeg?: number, toleranceMm?: number): void
```

#### `verify.faceAt()` — Check that a face center lies at a specific position (within toleranceMm).

```ts
verify.faceAt(label: string, face: FaceRefLike, expectedPos: [ number, number, number ], toleranceMm?: number): void
```

#### `verify.sameDirection()` — Check that two face normals point in the same direction (not antiparallel). Stricter than parallel — both |angle| AND sign must match.

```ts
verify.sameDirection(label: string, faceA: FaceRefLike, faceB: FaceRefLike, toleranceDeg?: number): void
```

#### `verify.isEmpty()` — Check that a shape is empty.

```ts
verify.isEmpty(label: string, shape: ShapeLike, message?: string): void
```

#### `verify.notEmpty()` — Check that a shape is NOT empty.

```ts
verify.notEmpty(label: string, shape: ShapeLike, message?: string): void
```

#### `verify.volumeApprox()` — Check that a shape's volume is approximately equal to expected (mm³).

```ts
verify.volumeApprox(label: string, shape: ShapeLike, expected: number, tolerance?: number): void
```

#### `verify.areaApprox()` — Check that a shape's surface area is approximately equal to expected (mm²).

```ts
verify.areaApprox(label: string, shape: ShapeLike, expected: number, tolerance?: number): void
```

#### `verify.boundingBoxSize()` — Check that a shape's bounding box has approximately the given size.

```ts
verify.boundingBoxSize(label: string, shape: ShapeLike, expectedSize: [ number, number, number ], tolerance?: number): void
```

#### `verify.edgeContinuity()` — Check that every sampled seam on a shape meets a requested continuity threshold.

```ts
verify.edgeContinuity(label: string, shape: ShapeLike, options?: EdgeContinuityThresholds): void
```

**`EdgeContinuityThresholds`**: `continuity?: SurfaceContinuity`, `samples?: number`, `positionTolerance?: number`, `tangentToleranceDeg?: number`, `curvatureTolerance?: number`

#### `verify.noTinyEdges()` — Check that a shape has no tiny edges below the requested threshold.

```ts
verify.noTinyEdges(label: string, shape: ShapeLike, threshold?: number): void
```

#### `verify.noSliverFaces()` — Check that a shape has no sliver faces below the requested score threshold.

```ts
verify.noSliverFaces(label: string, shape: ShapeLike, threshold?: number): void
```

#### `verify.noSelfIntersection()` — Best-effort exact-shape validity guard for self-intersections or broken B-Rep topology.

```ts
verify.noSelfIntersection(label: string, shape: ShapeLike): void
```

#### `spec()` — Create a named, reusable bundle of verification checks.

A spec groups related `verify.*` calls under a collapsible header in the Checks panel. This makes large check suites scannable. Specs can be applied to multiple shapes and can check relationships between parts.

Specs can be defined in separate `.forge.js` files and imported via `require()` to share them across models.

`spec.check()` returns a `SpecResult` — you can inspect it programmatically or ignore the return value and let the Checks panel show results.

```ts
const printable = spec("Fits printer bed", (shape) => {
  verify.notEmpty("Has geometry", shape);
  const bb = shape.boundingBox();
  verify.lessThan("Width  < 220mm", bb.max[0] - bb.min[0], 220);
  verify.lessThan("Depth  < 220mm", bb.max[1] - bb.min[1], 220);
  verify.lessThan("Height < 250mm", bb.max[2] - bb.min[2], 250);
});

// Reuse on multiple shapes
printable.check(bracket);
printable.check(standoff);

// Check relationships between parts
const fitSpec = spec("Assembly fit", (partA, partB) => {
  verify.notColliding("No interference", partA, partB, 10);
});
fitSpec.check(bracket, standoff);
```

**Spec-first workflow:** Write specs before building geometry. Checks go from red to green as you build — effectively TDD for CAD.

```ts
spec(name: string, checkFn: (...args: any[]) => void): Spec
```

**`Spec`**
- `name: string` — The display name of this spec

---

## Classes

### `Shape`

Core 3D solid shape. All operations are immutable and return new shapes.

Supports transforms (translate, rotate, scale, mirror, transform, rotateAround, pointAlong), booleans (add, subtract, intersect), cutting (split, splitByPlane, trimByPlane), shelling, anchor positioning (attachTo, onFace), placement references, and queries (volume, surfaceArea, boundingBox, isEmpty, numTri, geometryInfo).

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `materialProps` | `ShapeMaterialProps | undefined` | — |

**Appearance**

#### `color()` — Set the color of this shape (hex string, e.g. "#ff0000"). Returns a new Shape with the color applied.

```ts
color(value: string | undefined): Shape
```

#### `material()` — Set PBR material properties for this shape's visual appearance.

Returns a new Shape with the specified material properties merged on top of any previously set properties. All properties are optional — omitted keys retain their current value. Material properties survive transforms and boolean operations.

Use `.color()` to set the base diffuse color; `.material()` controls how that color behaves under light (metalness, roughness, clearcoat) and can add emissive glow independent of lighting. Emissive glow pairs naturally with the `postProcessing.bloom` effect in [`scene()`](/docs/viewport#scene).

```js
box(50, 50, 50).material({ metalness: 0.9, roughness: 0.1 }); // polished metal
sphere(30).material({ emissive: '#ff6b35', emissiveIntensity: 2 }); // glowing
cylinder(40, 20).material({ opacity: 0.4, clearcoat: 1.0, clearcoatRoughness: 0.02 }); // ice

// Chainable with other shape methods
box(100, 100, 10).color('#gold').material({ metalness: 0.95, roughness: 0.05 }).translate(0, 0, 50);
```

```ts
material(props: ShapeMaterialProps): Shape
```

**Face Topology**

#### `face()` — Resolve a face by user-authored label or compiler-owned name. Returns a `FaceRef` that can be passed to `.onFace()`, `projectToPlane()`, or used directly in placement.

`.face(name)` is a pure label lookup — it finds faces by user-authored labels, not by geometric queries. Labels are born in sketches via `.label()` / `.labelEdges()` and grow into face names through extrude, loft, revolve, and sweep. They are stable references that travel with the geometry.

Labels must be unique within a shape. Use `.prefixLabels()` before combining shapes with `union()` / `difference()` to avoid collisions. Collision detection throws a clear error with a fix suggestion.

For compile-covered shapes (extrude, loft, etc.) the lookup resolves via the shape's compile plan. As a fallback, planar-faced mesh shapes (e.g. results of boolean ops) are resolved via coplanar triangle clustering.

```ts
// Edge labels become side face names after extrude
const profile = path()
  .moveTo(0, 0)
  .lineTo(100, 0).label('floor')
  .lineTo(100, 50).label('wall')
  .lineTo(0, 50).label('ceiling')
  .closeLabel('left-wall');
const room = profile.extrude(30, { labels: { start: 'base', end: 'top' } });
room.face('floor');   // side face from the labeled edge
room.face('base');    // base cap (user-specified)

// .labelEdges() shorthand for sequential edge labeling
const plate = rect(100, 50).labelEdges('south', 'east', 'north', 'west');
const solid = plate.extrude(20, { labels: { start: 'bottom', end: 'top' } });
solid.face('south'); // side face

// Prefix before combining to avoid collisions
const left = wing.prefixLabels('l/');
const right = wing.mirror([1, 0, 0]).prefixLabels('r/');
const full = union(left, right);
full.face('l/upper'); // left wing upper surface
```

```ts
face(selector: FaceSelector): FaceRef
```

#### `faces()` — Return faces matching a query, or label semantic faces when passed a mapping.

Mapping form returns a new shape: `shape.faces({ lid: 'top', walls: ['front', 'back', 'left', 'right'] })`.

```ts
faces(): FaceRef[]
```

#### `faceNames()` — List defined semantic face names currently available on this shape.

```ts
faceNames(): string[]
```

#### `prefixLabels()` — Prefix all user-authored face labels, including semantic labels from `faces(mapping)`. Returns a new shape with modified labels.

```ts
prefixLabels(prefix: string): Shape
```

#### `renameLabel()` — Rename a single face label. Returns a new shape.

```ts
renameLabel(from: string, to: string): Shape
```

#### `dropLabels()` — Remove specific face labels. Returns a new shape.

```ts
dropLabels(...names: string[]): Shape
```

#### `dropAllLabels()` — Remove all face labels. Returns a new shape.

```ts
dropAllLabels(): Shape
```

#### `faceHistory()` — Get the transformation history for a specific face.

```ts
faceHistory(name: string): FaceTransformationHistory
```

**Edge Topology**

#### `edge()` — Get a named topology edge. Only available on shapes with tracked topology (from box/cylinder/extrude).

```ts
edge(name: string): EdgeRef
```

#### `edgeNames()` — List named topology edge names. Returns empty array if shape has no tracked topology.

```ts
edgeNames(): string[]
```

#### `edgesOf()` — Return all boundary edges of a named face.

Finds edges where one adjacent mesh face belongs to the target face and the other belongs to a different face. The result is coalesced (tessellation fragments merged) and can be passed directly to `fillet()` or `chamfer()`.

This is a topological query — no coordinates, no tolerances, no minimum-length hacks. It works because an edge is the boundary between two faces.

```js
// Fillet all top edges of a mounting plate
let plate = box(120, 80, 6).faces({ workSurface: 'top' })
plate = fillet(plate, 3, plate.edgesOf('workSurface'))

// Shelled enclosure — fillet the outer lip
let body = box(80, 50, 35).faces({ opening: 'top' })
body = body.shell(2, { openFaces: ['top'] })
body = fillet(body, 1.5, body.edgesOf('opening'))

// Filter: only concave edges (after a boolean subtraction)
body.edgesOf('top', { concave: true })
```

```ts
edgesOf(faceLabel: string, options?: EdgesOfOptions): EdgeSegment[]
```

#### `edgesBetween()` — Return edges shared between two named faces.

An edge is "between" faces A and B when one of its adjacent mesh triangles belongs to A and the other belongs to B. This is the most precise topological edge selection — "fillet the edges where the top meets the wall."

The second argument can be a single face name or an array (edges between A and any of B1, B2, ...).

```js
// Fillet the edge where lid meets one wall
let body = box(100, 60, 30).faces({ lid: 'top', wall: 'side-left' })
body = fillet(body, 2, body.edgesBetween('lid', 'wall'))

// Fillet a cylinder rim — where the flat cap meets the curved barrel
let tube = cylinder(30, 10).faces({ cap: 'top', barrel: 'side' })
tube = fillet(tube, 1, tube.edgesBetween('cap', 'barrel'))

// Multiple target faces at once
body.edgesBetween('lid', ['left-wall', 'right-wall', 'front-wall', 'back-wall'])
```

```ts
edgesBetween(faceA: string, faceB: string | string[]): EdgeSegment[]
```

**Transforms**

#### `translate()` — Move the shape relative to its current position. All transforms are immutable and return new shapes.

```ts
translate(x: number, y: number, z: number): Shape
```

#### `translatePolar()` — Translate using polar coordinates (radius + angle in degrees). Eliminates manual `r * Math.cos(angle * PI/180)` calculations.

Example: `shape.translatePolar(50, 30)` moves 50mm at 30 degrees from +X.

```ts
translatePolar(radius: number, angleDeg: number, z?: number): Shape
```

#### `moveTo()` — Position the shape so its bounding box min corner is at the given global coordinate.

```ts
moveTo(x: number, y: number, z: number): Shape
```

#### `moveToLocal()` — Position the shape relative to another shape's local coordinate system (bounding box min corner).

```ts
moveToLocal(target: Shape | { toShape(): Shape; }, x: number, y: number, z: number): Shape
```

#### `rotate()` — Rotate around an arbitrary axis through the origin.

```ts
rotate(axis: [ number, number, number ], angleDeg: number, options?: { pivot?: [ number, number, number ]; }): Shape
```

#### `rotateX()` — Rotate around the X axis by the given angle in degrees.

```ts
rotateX(angleDeg: number, options?: { pivot?: [ number, number, number ]; }): Shape
```

#### `rotateY()` — Rotate around the Y axis by the given angle in degrees.

```ts
rotateY(angleDeg: number, options?: { pivot?: [ number, number, number ]; }): Shape
```

#### `rotateZ()` — Rotate around the Z axis by the given angle in degrees.

```ts
rotateZ(angleDeg: number, options?: { pivot?: [ number, number, number ]; }): Shape
```

#### `rotateAroundTo()` — Rotate around an axis until a moving point reaches the target line/plane defined by the axis and target point. `movingPoint` / `targetPoint` may be raw world points or this shape's anchors/references.

```ts
rotateAroundTo(axis: [ number, number, number ], pivot: [ number, number, number ], movingPoint: RotationPointLike, targetPoint: RotationPointLike, options?: RotateAroundToOptions): Shape
```

#### `transform()` — Apply a 4x4 affine transform matrix (column-major) or a Transform object.

```ts
transform(m: Mat4 | Transform): Shape
```

#### `scale()` — Scale the shape uniformly or per-axis from the shape's bounding box center. Accepts a single number or [x, y, z] array.

```ts
scale(v: number | [ number, number, number ]): Shape
```

#### `scaleAround()` — Scale the shape uniformly or per-axis from an explicit pivot point.

```ts
scaleAround(pivot: [ number, number, number ], v: number | [ number, number, number ]): Shape
```

#### `mirror()` — Mirror across a plane through the shape's bounding box center, defined by its normal vector.

```ts
mirror(normal: [ number, number, number ]): Shape
```

#### `mirrorThrough()` — Mirror across a plane through an explicit point, defined by its normal vector.

```ts
mirrorThrough(point: [ number, number, number ], normal: [ number, number, number ]): Shape
```

#### `pointAlong()` — Reorient a shape so its primary axis (Z) points along the given direction. Useful for laying cylinders/extrusions along X or Y without thinking about Euler angles. The shape's origin stays at [0,0,0] — translate after pointAlong to position it.

Example: cylinder(40, 5).pointAlong([1, 0, 0]) — lays cylinder along X, starting at origin

```ts
pointAlong(direction: [ number, number, number ]): Shape
```

**Booleans & Cutting**

#### `add()` — Union this shape with others (additive boolean). Method form of union().

```ts
add(...others: ShapeOperandInput[]): Shape
```

#### `subtract()` — Subtract other shapes from this one. Method form of difference().

```ts
subtract(...others: ShapeOperandInput[]): Shape
```

#### `intersect()` — Keep only the overlap with other shapes. Method form of intersection().

```ts
intersect(...others: ShapeOperandInput[]): Shape
```

#### `split()` — Split into [inside, outside] by another shape.

```ts
split(cutter: Shape | { toShape(): Shape; }): [ Shape, Shape ]
```

#### `splitByPlane()` — Split by infinite plane. Returns [positive-side, negative-side].

```ts
splitByPlane(normal: [ number, number, number ], originOffset?: number): [ Shape, Shape ]
```

#### `trimByPlane()` — Keep the positive side of the plane and discard the opposite side.

```ts
trimByPlane(normal: [ number, number, number ], originOffset?: number): Shape
```

**Features**

#### `shell()` — Hollow out compile-covered boxes, cylinders, and straight extrudes. `openFaces` names any subset of the base shape's labeled faces to leave open (no wall).

```ts
shell(thickness: number, opts?: { openFaces?: string[]; }): Shape
```

#### `pocket()` — Cut a pocket (cavity) into this solid through the named face.

```js
box(100, 100, 20).pocket('top', 8)
box(100, 100, 20).pocket('top', 8, { inset: 5 })
box(100, 100, 20).pocket('top', 8, { scale: 0.8 })
```

```ts
pocket(face: FaceSelector, depth: number, opts?: PocketOptions): Shape
```

#### `boss()` — Add a boss (protrusion) from the named face.

```js
box(100, 100, 20).boss('top', 5)
box(100, 100, 20).boss('top', 10, { scale: 0.6 })
```

```ts
boss(face: FaceSelector, height: number, opts?: BossOptions): Shape
```

#### `hole()` — Drill a hole into this solid at a face.

```js
box(50, 50, 20).hole('top', { diameter: 8, depth: 10 })
box(50, 50, 20).hole('top', { diameter: 6, counterbore: { diameter: 12, depth: 3 } })
```

```ts
hole(faceOrRef: SketchFaceTarget | FaceRef, opts: ShapeHoleOptions): Shape
```

#### `cutout()` — Cut a profile-shaped pocket through a face using a placed sketch.

The sketch must be placed on a face with `Sketch.onFace(...)`. The cut follows the sketch's 2D profile.

```js
const profile = circle2d(10).onFace(body, 'top');
body.cutout(profile, { depth: 5 })
```

```ts
cutout(sketch: Sketch, opts?: ShapeCutoutOptions): Shape
```

**Placement**

#### `placeReference()` — Translate the shape so the given anchor or reference lands on the target coordinate.

Accepts any built-in anchor name (`'bottom'`, `'center'`, `'top-front-left'`, etc.) or a custom placement reference attached via `withReferences()`.

```javascript
// Ground a shape — put its bottom face center at Z = 0
shape.placeReference('bottom', [0, 0, 0])

// Center at the world origin
shape.placeReference('center', [0, 0, 0])

// Align left edge to X = 10
shape.placeReference('left', [10, 0, 0])
```

```ts
placeReference(ref: PlacementAnchorLike, target: [ number, number, number ], offset?: [ number, number, number ]): Shape
```

#### `attachTo()` — Position this shape relative to another using named 3D anchor points.

Anchors are bounding-box-relative: 'center', face centers ('top', 'front', ...), edge midpoints ('top-front', 'back-left', ...), and corners ('top-front-left', ...). Anchor word order is flexible: 'front-left' and 'left-front' are equivalent. Named placement references (from withReferences) can also be used as anchors.

```ts
attachTo(target: ShapeAnchorTarget, targetAnchor: PlacementAnchorLike, selfAnchor?: PlacementAnchorLike, offset?: [ number, number, number ]): Shape
```

#### `onFace()` — Place this shape on a face of a parent shape.

Think of it like sticking a label on a box surface:

- `face` picks which surface ('front', 'back', 'top', etc.)
- `u, v` position within that face's 2D plane (from center)
- front/back: u = left/right (X), v = up/down (Z)
- left/right: u = forward/back (Y), v = up/down (Z)
- top/bottom: u = left/right (X), v = forward/back (Y)
- `protrude` = how far the child sticks out (positive = outward from face)

```ts
onFace(parent: ShapeAnchorTarget, face: "front" | "back" | "left" | "right" | "top" | "bottom", opts?: { u?: number; v?: number; protrude?: number; }): Shape
```

#### `seatInto()` — Slide this shape along an axis until a labeled face is embedded in the target body.

Position the shape roughly first (translate/rotate), then call seatInto to auto-adjust the penetration depth. No manual coordinate math needed.

```js
// Wing root embeds into fuselage — adapts to any fuselage shape
wing.translate(0, wingY, 0).seatInto(fuselage, 'root');

// Sensor pod sits flush on fuselage surface
pod.translate(0, station, radius + 20).seatInto(fuselage, 'base', { depth: 'flush' });

// Antenna with 3mm gasket standoff
mast.translate(0, station, radius + 50).seatInto(fuselage, 'mount', { depth: 'flush', gap: 3 });
```

```ts
seatInto(target: Shape, surface: string, options?: SeatIntoOptions): Shape
```

#### `seatOver()` — Slide this shape until a target's labeled face is fully covered (inside this shape).

The inverse of `seatInto`: instead of embedding *your* face into the target, you move until the *target's* face is embedded inside you.

```js
// Nacelle moves up until pylon's bottom face is inside the nacelle
nacelle.translate(rough).seatOver(pylon, 'bottom');

// Cap slides down over a post until post's top face is covered
cap.translate(rough).seatOver(post, 'top');
```

```ts
seatOver(target: Shape, targetSurface: string, options?: SeatIntoOptions): Shape
```

**Connectors**

#### `withConnectors()` — Attach named connectors — attachment points that survive transforms and imports. Connectors can be bare (position + orientation) or typed (with connectorType/gender for compatibility matching).

```ts
withConnectors(connectors: Record<string, ConnectorInput>): Shape
```

#### `connectorNames()` — List all connector names on this shape.

```ts
connectorNames(): string[]
```

#### `connectorsByType()` — Get all connectors of a given type.

```ts
connectorsByType(type: string): Array<{ name: string; port: ConnectorDef; }>
```

#### `connectorDistance()` — Distance between two connector origins on this shape.

```ts
connectorDistance(nameA: string, nameB: string): number
```

#### `connectorMeasurements()` — Get measurements metadata from a connector.

```ts
connectorMeasurements(name: string): Record<string, number | string>
```

#### `matchTo()` — Position this shape by matching connectors to a target.

Overloads:

- Single pair: `matchTo(target, selfConn, targetConn, options?)`
- Dictionary (same target): `matchTo(target, { selfConn: targetConn, ... }, options?)`
- Multi-target: `matchTo([ [target1, selfConn1, targetConn1], ... ], options?)`

```ts
matchTo(targetOrPairs: Shape | MatchTarget | Array<[ Shape | MatchTarget, string, string ]>, selfConnOrDict?: string | Record<string, string>, targetConnOrOptions?: string | MatchToOptions, maybeOptions?: MatchToOptions): Shape
```

**References**

#### `withReferences()` — Attach named placement references that survive normal transforms and imports.

```ts
withReferences(refs: PlacementReferenceInput): Shape
```

#### `referenceNames()` — List named placement references carried by this shape.

```ts
referenceNames(kind?: PlacementReferenceKind): string[]
```

#### `referencePoint()` — Resolve a named placement reference or built-in anchor to a 3D point.

```ts
referencePoint(ref: PlacementAnchorLike): [ number, number, number ]
```

**Measurement**

#### `boundingBox()` — Get the axis-aligned bounding box as { min: [x,y,z], max: [x,y,z] }.

```ts
boundingBox(): ShapeRuntimeBounds
```

#### `volume()` — Volume in mm cubed.

```ts
volume(): number
```

#### `surfaceArea()` — Surface area in mm squared.

```ts
surfaceArea(): number
```

#### `isEmpty()` — True if the shape contains no geometry.

```ts
isEmpty(): boolean
```

#### `numBodies()` — Number of disconnected solid bodies in this shape.

```ts
numBodies(): number
```

#### `numTri()` — Triangle count of the mesh representation.

```ts
numTri(): number
```

**Other**

#### `clone()` — Return a new Shape wrapper for explicit duplication in scripts.

```ts
clone(): Shape
```

#### `geometryInfo()` — Inspect which backend/representation produced this solid.

```ts
geometryInfo(): GeometryInfo
```

#### `as()` — Name this shape as a reference namespace for diagnostics and future published refs.

```ts
as(name: string): Shape
```

#### `ref()` — Resolve a semantic reference path like `lid`, `lid/back`, or a midpoint selector on `lid/back`.

```ts
ref(path: string): ShapeRef
```

#### `thicken()` — Offset-thicken an exact open surface or shell into a solid.

```ts
thicken(thickness: number): Shape
```

#### `getMesh()` — Extract triangle mesh for Three.js rendering

```ts
getMesh(): ShapeRuntimeMesh
```

#### `slice()` — Slice the runtime solid by a plane normal to local Z at the given offset.

```ts
slice(offset?: number): any
```

#### `project()` — Orthographically project the runtime solid onto the local XY plane.

```ts
project(): any
```

**Legacy Aliases**

- `withPorts()` -> `withConnectors()`
- `portNames()` -> `connectorNames()`

### `Transform`

#### `identity()` — Return the identity transform.

```ts
static identity(): Transform
```

#### `from()` — Wrap an existing `Transform` or raw 4x4 matrix as a `Transform`.

```ts
static from(input: TransformInput): Transform
```

#### `translation()` — Create a translation transform.

```ts
static translation(x: number, y: number, z: number): Transform
```

#### `scale()` — Create a uniform or per-axis scale transform.

```ts
static scale(v: number | Vec3): Transform
```

#### `rotationAxis()` — Create a rotation around an arbitrary axis, optionally about a pivot.

```ts
static rotationAxis(axis: Vec3, angleDeg: number, pivot?: Vec3): Transform
```

#### `rotateAroundTo()` — Solve the rotation needed to move one point onto a target line or plane.

```ts
static rotateAroundTo(axis: Vec3, pivot: Vec3, movingPoint: Vec3, targetPoint: Vec3, options?: RotateAroundToOptions): Transform
```

#### `mul()` — Compose transforms in chain order: `a.mul(b)` applies `a`, then `b`.

```ts
mul(other: TransformInput): Transform
```

#### `translate()` — Translate after the current transform.

```ts
translate(x: number, y: number, z: number): Transform
```

#### `rotateAxis()` — Rotate after the current transform.

```ts
rotateAxis(axis: Vec3, angleDeg: number, pivot?: Vec3): Transform
```

#### `inverse()` — Return the inverse transform.

```ts
inverse(): Transform
```

#### [`point()`](/docs/sketch#point) — Transform a point using homogeneous coordinates.

```ts
point(p: Vec3): Vec3
```

#### `vector()` — Transform a direction vector without translation.

```ts
vector(v: Vec3): Vec3
```

#### `toArray()` — Return the transform as a raw 4x4 matrix array.

```ts
toArray(): Mat4
```

### `ShapeGroup`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `children` | `GroupChild[]` | — |
| `childNames` | `Array<string | undefined>` | — |

**Children**

#### `child()` — Return the named child by name. Throws if not found. Useful when importing a multipart group and working on components individually.

```ts
child(name: string): GroupChild
```

#### `childName()` — Return the optional name of the child at `index`.

```ts
childName(index: number): string | undefined
```

**Transforms**

#### `translate()` — Move the entire group by (x, y, z). All children move together as a unit.

```ts
translate(x: number, y: number, z: number): ShapeGroup
```

#### `moveTo()` — Move the group so its bounding-box min corner lands at the given coordinate.

```ts
moveTo(x: number, y: number, z: number): ShapeGroup
```

#### `moveToLocal()` — Move the group relative to another part's bounding-box min corner.

```ts
moveToLocal(target: Shape | ShapeGroup, x: number, y: number, z: number): ShapeGroup
```

#### `rotate()` — Rotate the group around an arbitrary axis through the origin.

```ts
rotate(axis: [ number, number, number ], angleDeg: number, options?: { pivot?: [ number, number, number ]; }): ShapeGroup
```

#### `rotateX()` — Rotate the group around the X axis.

```ts
rotateX(angleDeg: number, options?: { pivot?: [ number, number, number ]; }): ShapeGroup
```

#### `rotateY()` — Rotate the group around the Y axis.

```ts
rotateY(angleDeg: number, options?: { pivot?: [ number, number, number ]; }): ShapeGroup
```

#### `rotateZ()` — Rotate the group around the Z axis.

```ts
rotateZ(angleDeg: number, options?: { pivot?: [ number, number, number ]; }): ShapeGroup
```

#### `rotateAroundAxis()` — Rotate around an arbitrary axis, optionally through a pivot point.

```ts
rotateAroundAxis(axis: [ number, number, number ], angleDeg: number, pivot?: [ number, number, number ]): ShapeGroup
```

#### `rotateAroundTo()` — Rotate around an axis until a moving point reaches the target line/plane defined by the axis and target point. ShapeGroup string points use built-in anchors only.

```ts
rotateAroundTo(axis: [ number, number, number ], pivot: [ number, number, number ], movingPoint: Anchor3D | [ number, number, number ], targetPoint: Anchor3D | [ number, number, number ], options?: RotateAroundToOptions): ShapeGroup
```

#### `pointAlong()` — Reorient the group so its local Z axis points along `direction`.

```ts
pointAlong(direction: [ number, number, number ]): ShapeGroup
```

#### `transform()` — Apply a 4x4 transform matrix or `Transform` to all 3D children.

```ts
transform(m: Mat4 | Transform): ShapeGroup
```

#### `scale()` — Scale uniformly or per-axis from the group's bounding-box center.

```ts
scale(v: number | [ number, number, number ]): ShapeGroup
```

#### `scaleAround()` — Scale uniformly or per-axis from an explicit pivot point.

```ts
scaleAround(pivot: [ number, number, number ], v: number | [ number, number, number ]): ShapeGroup
```

#### `mirror()` — Mirror across a plane through the group's bounding-box center.

```ts
mirror(normal: [ number, number, number ]): ShapeGroup
```

#### `mirrorThrough()` — Mirror across a plane through an explicit point.

```ts
mirrorThrough(point: [ number, number, number ], normal: [ number, number, number ]): ShapeGroup
```

**Placement**

#### `placeReference()` — Translate the group so the given anchor or reference lands on the target coordinate.

Accepts any built-in anchor name (`'bottom'`, `'center'`, `'top-front-left'`, etc.) or a custom placement reference attached via `withReferences()`.

```javascript
// Ground a group — put its bottom at Z = 0
assembly.placeReference('bottom', [0, 0, 0])

// Use a custom reference from a multi-file part
const placed = require('./bracket-assembly.forge.js').group
  .placeReference('mountCenter', [0, 0, 50]);
```

```ts
placeReference(ref: PlacementAnchorLike, target: [ number, number, number ], offset?: [ number, number, number ]): ShapeGroup
```

#### `attachTo()` — Attach this group to a face or anchor on another part.

`targetAnchor` can be a built-in anchor name or a custom reference name on the target. `selfAnchor` selects the anchor on this group to align.

```ts
attachTo(target: Shape | ShapeGroup, targetAnchor: Anchor3D | string, selfAnchor?: Anchor3D, offset?: [ number, number, number ]): ShapeGroup
```

#### `onFace()` — Place this group on a face of a parent shape. See Shape.onFace() for full documentation.

```ts
onFace(parent: Shape | ShapeGroup, face: "front" | "back" | "left" | "right" | "top" | "bottom", opts?: { u?: number; v?: number; protrude?: number; }): ShapeGroup
```

**Connectors**

#### `withConnectors()` — Attach named connectors — attachment points that survive transforms. Connectors can be bare (position + orientation) or typed (with connectorType/gender for compatibility matching).

```ts
withConnectors(connectors: Record<string, ConnectorInput>): ShapeGroup
```

#### `connectorNames()` — List all connector names, including "ChildName.connectorName" from named children.

```ts
connectorNames(): string[]
```

#### `connectorsByType()` — Get all connectors of a given type, including from named children.

```ts
connectorsByType(type: string): Array<{ name: string; port: ConnectorDef; }>
```

#### `connectorDistance()` — Distance between two connector origins on this group (supports dotted child paths).

```ts
connectorDistance(nameA: string, nameB: string): number
```

#### `connectorMeasurements()` — Get measurements metadata from a connector (supports dotted child paths).

```ts
connectorMeasurements(name: string): Record<string, number | string>
```

#### `matchTo()` — Position this group by matching connectors to a target. Connector names support dotted paths into named children: "ChildName.connectorName".

Overloads:

- Single pair: `matchTo(target, selfConn, targetConn, options?)`
- Dictionary (same target): `matchTo(target, { selfConn: targetConn, ... }, options?)`
- Multi-target: `matchTo([ [target1, selfConn1, targetConn1], ... ], options?)`

```ts
matchTo(targetOrPairs: Shape | ShapeGroup | Array<[ Shape | ShapeGroup, string, string ]>, selfConnOrDict?: string | Record<string, string>, targetConnOrOptions?: string | MatchToOptions, maybeOptions?: MatchToOptions): ShapeGroup
```

**References**

#### `withReferences()` — Attach named placement references to this group. References survive normal transforms (translate/rotate/scale/mirror/transform).

```javascript
const bracket = group(
  { name: 'Left', shape: leftShape },
  { name: 'Right', shape: rightShape },
).withReferences({
  points: { mountCenter: [0, 0, 0] },
});
```

```ts
withReferences(refs: PlacementReferenceInput): ShapeGroup
```

#### `referenceNames()` — List named placement references carried by this group.

```ts
referenceNames(kind?: PlacementReferenceKind): string[]
```

#### `referencePoint()` — Resolve a named placement reference or built-in Anchor3D to a 3D point. Named refs take priority over built-in anchors.

```ts
referencePoint(ref: PlacementAnchorLike): [ number, number, number ]
```

**Other**

#### `clone()` — Return a deep-cloned ShapeGroup tree (refs copied).

```ts
clone(): ShapeGroup
```

#### `boundingBox()` — Return the combined 3D bounding box of all children.

```ts
boundingBox(): { min: [ number, number, number ]; max: [ number, number, number ]; }
```

#### `color()` — Return a copy of the group with the given display color applied to each child.

```ts
color(hex: string): ShapeGroup
```

**Legacy Aliases**

- `withPorts()` -> `withConnectors()`
- `portNames()` -> `connectorNames()`

### `SurfacePattern`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `body` | `string` | Function body: receives (u, v) in surface mm, returns height displacement. |
| `constants` | `Record<string, number>` | Named constants injected into the function. |

### `Pattern2D`

#### `add()` — Add this pattern to one or more patterns or constant height offsets.

```ts
add(...patterns: Pattern2DInput[]): Pattern2D
```

#### `subtract()` — Subtract another pattern or constant height offset from this pattern.

```ts
subtract(pattern: Pattern2DInput): Pattern2D
```

#### `multiply()` — Multiply this pattern by one or more patterns or numeric scale factors.

```ts
multiply(...patterns: Pattern2DInput[]): Pattern2D
```

#### `min()` — Keep the lower height between this pattern and one or more other patterns.

```ts
min(...patterns: Pattern2DInput[]): Pattern2D
```

#### `max()` — Keep the higher height between this pattern and one or more other patterns.

```ts
max(...patterns: Pattern2DInput[]): Pattern2D
```

#### `clamp()` — Limit pattern height to the inclusive `[min, max]` range in millimeters.

```ts
clamp(min: number, max: number): Pattern2D
```

#### `abs()` — Convert negative heights to positive heights.

```ts
abs(): Pattern2D
```

#### `negate()` — Flip the pattern height sign.

```ts
negate(): Pattern2D
```

### `Pattern2DBuilder`

#### `constant()` — Create a constant-height pattern in millimeters.

```ts
constant(value?: number): Pattern2D
```

#### `sineWave()` — Create a sinusoidal wave pattern in UV space.

```ts
sineWave(options: Pattern2DSineWaveOptions): Pattern2D
```

#### `stripes()` — Create recessed stripe bands in UV space.

```ts
stripes(options: Pattern2DStripesOptions): Pattern2D
```

#### `overUnderWeave()` — Create an over-under woven relief pattern in UV space.

```ts
overUnderWeave(options: Pattern2DOverUnderWeaveOptions): Pattern2D
```

### `ShapeRef`

A first-class reference path over a shape's semantic faces and face relationships.

Created with `shape.ref("lid/back")`, then refined through methods such as `.point()` or `.edges()`. The reference stores intent as a readable path and resolves lazily against the current shape metadata.

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `path` | `string` | — |

**Methods:**

#### `resolve()` — Resolve this reference into its current faces, edges, or points.

```ts
resolve(): ShapeReferenceResolution
```

#### `kind()` — The resolved reference kind, such as `face`, `edge-set`, or [`point`](/docs/sketch#point).

```ts
get kind(): ShapeReferenceKind
```

#### `cardinality()` — Whether the reference currently resolves to zero, one, or many matches.

```ts
get cardinality(): ShapeReferenceCardinality
```

#### `status()` — Return the reference lifecycle status for the current shape state.

```ts
status(): ShapeReferenceStatus
```

#### `explain()` — Return a human-readable explanation of how this reference resolved.

```ts
explain(): string
```

#### `as()` — Name this derived reference so the same shape can resolve it by `shape.ref(name)`.

```ts
as(name: string): ShapeRef
```

#### `maybe()` — Return an optional reference that resolves to zero matches instead of throwing when missing.

```ts
maybe(): ShapeRef
```

#### `all()` — Mark that a multi-match reference is intentionally being used as a set.

```ts
all(): ShapeRef
```

#### `one()` — Require this reference to resolve to exactly one match.

```ts
one(): ShapeRef
```

#### `faces()` — Resolve this reference as one or more faces.

```ts
faces(): FaceRef[]
```

#### `face()` — Resolve this reference as exactly one face.

```ts
face(): FaceRef
```

#### `edges()` — Resolve this reference as one or more edges. Face references return boundary edges.

```ts
edges(): EdgeSegment[]
```

#### `edge()` — Resolve this reference as exactly one edge.

```ts
edge(): EdgeSegment
```

#### `points()` — Resolve this reference as one or more points. Faces use centers and edges use midpoints.

```ts
points(): Vec3[]
```

#### [`point()`](/docs/sketch#point) — Resolve this reference as exactly one point.

```ts
point(): Vec3
```

#### `toJSON()` — Return the structured JSON-friendly reference resolution.

```ts
toJSON(): ShapeReferenceResolution
```

#### `toString()` — Return a compact display form for this reference path.

```ts
toString(): string
```

---

## Constants

### `ANCHOR3D_NAMES`

### `verify`

- `that(label: string, check: () => boolean, message?: string): void` — Custom predicate check.
- `equal(label: string, actual: number, expected: number, tolerance?: number, message?: string): void` — Check that two numbers are approximately equal (within tolerance).
- `notEqual(label: string, actual: number, unexpected: number, tolerance?: number, message?: string): void` — Check that two numbers are NOT equal (differ by more than tolerance).
- `greaterThan(label: string, actual: number, min: number, message?: string): void` — Check that actual > min.
- `lessThan(label: string, actual: number, max: number, message?: string): void` — Check that actual < max.
- `inRange(label: string, actual: number, min: number, max: number, message?: string): void` — Check that min <= actual <= max.
- `centersCoincide(label: string, a: ShapeLike, b: ShapeLike, tolerance?: number): void` — Check that the bounding-box centers of two shapes coincide within tolerance (mm).
- `connectorDistance(label: string, target: ConnectorDistanceLike, connectorA: string, connectorB: string, expected?: number, tolerance?: number): void` — Check the distance between two named connectors on a shape or group. Use this when connectors + `matchTo()` define a static assembly interface. It proves the mate at runtime, unlike a plain source-level connector declaration. The common case is `expected = 0`, meaning the two connector origins should coincide after placement. **Example** ```ts verify.connectorDistance("leg is seated", bench, "Rail.leg_0", "Leg0.head", 0, 0.01); ```
- `physicalComponentCount(label: string, expected: number): void` — Declare the expected physical connectivity component count for the returned visible model. **Details** Use this for generated mechanical models that should have a clear component graph: one connected fixture, a purchased part plus a removable cartridge, a root assembly plus named intentional ghosts, and so on. `forgecad inspect mechanical-integrity` resolves the returned visible objects with the same physical-connectivity analysis used in the quality gate and fails if the actual component count differs. This catches the common generated-CAD failure where a script returns a visually plausible artifact but the handle, screw, washer, cover, or terminal block is actually a separate island. **Example** ```ts verify.physicalComponentCount("vise is one connected installed assembly", 1); ```
- `intentionalOverlap(label: string, a: ShapeLike, b: ShapeLike, reason: string): void` — Declare that two visible objects intentionally overlap because the overlap is real manufacturing intent. **Details** Use this only for overlaps that a mechanical reviewer would accept as actual matter sharing volume: welded/fused regions, overmolded inserts, potted electronics, cast-in hardware, or deliberately bonded laminations. This is not a shortcut for screws without holes, shafts without bores, covers without pockets, or parts placed with collision as a positioning hack. `forgecad inspect mechanical-integrity --collisions` only honors this declaration when both shapes are returned as visible objects and the exact collision report finds that same object pair. Unused or non-visible declarations fail the quality gate so annotations cannot hide unrelated collisions. **Example** ```ts verify.intentionalOverlap("rubber grip is overmolded on handle", rubberGrip, handleCore, "overmolded insert"); ```
- `notColliding(label: string, a: ShapeLike, b: ShapeLike, searchLength?: number): void` — Check that two shapes do not collide (minGap > 0).
- `minClearance(label: string, a: ShapeLike, b: ShapeLike, minGap: number, searchLength?: number): void` — Check that a minimum clearance gap exists between two shapes.
- `clearanceBetween(label: string, a: ShapeLike, b: ShapeLike, minGap: number, maxGap: number, searchLength?: number): void` — Check that the clearance gap between two shapes is inside an allowed range. **Details** Use this for seated and retained interfaces where a part must be close enough to be mechanically accountable, but must not collide beyond the allowed minimum. It catches both failure modes that make generated CAD look fake: parts floating away from their receiver, and parts intersecting their receiver because the pocket, bore, or running clearance was not modeled. For contact, use a narrow range such as `[-0.01, 0.05]` to tolerate tiny numerical noise. For a running fit, use the intended clearance band. Manifold-backed shapes use exact min-gap distance. Other backends use a mesh-derived min-gap check and say so in the verification message; keep `forgecad inspect mechanical-integrity --collisions` in the acceptance gate for positive-volume interference. **Example** ```ts verify.clearanceBetween("cover is seated on gasket", cover, gasket, -0.01, 0.05); verify.clearanceBetween("carriage runs inside rail", carriage, rail, 0.2, 0.5); ```
- `parallel(label: string, faceA: FaceRefLike, faceB: FaceRefLike, toleranceDeg?: number): void` — Check that two face normals are parallel (within toleranceDeg degrees).
- `perpendicular(label: string, faceA: FaceRefLike, faceB: FaceRefLike, toleranceDeg?: number): void` — Check that two face normals are perpendicular (within toleranceDeg degrees).
- `coplanar(label: string, faceA: FaceRefLike, faceB: FaceRefLike, toleranceDeg?: number, toleranceMm?: number): void` — Check that a face is coplanar with (same plane as) another face, meaning they are parallel AND their centers lie on the same plane.
- `faceAt(label: string, face: FaceRefLike, expectedPos: [ number, number, number ], toleranceMm?: number): void` — Check that a face center lies at a specific position (within toleranceMm).
- `sameDirection(label: string, faceA: FaceRefLike, faceB: FaceRefLike, toleranceDeg?: number): void` — Check that two face normals point in the same direction (not antiparallel). Stricter than parallel — both |angle| AND sign must match.
- `isEmpty(label: string, shape: ShapeLike, message?: string): void` — Check that a shape is empty.
- `notEmpty(label: string, shape: ShapeLike, message?: string): void` — Check that a shape is NOT empty.
- `volumeApprox(label: string, shape: ShapeLike, expected: number, tolerance?: number): void` — Check that a shape's volume is approximately equal to expected (mm³).
- `areaApprox(label: string, shape: ShapeLike, expected: number, tolerance?: number): void` — Check that a shape's surface area is approximately equal to expected (mm²).
- `boundingBoxSize(label: string, shape: ShapeLike, expectedSize: [ number, number, number ], tolerance?: number): void` — Check that a shape's bounding box has approximately the given size.
- `edgeContinuity(label: string, shape: ShapeLike, options?: EdgeContinuityThresholds): void` — Check that every sampled seam on a shape meets a requested continuity threshold.
- `noTinyEdges(label: string, shape: ShapeLike, threshold?: number): void` — Check that a shape has no tiny edges below the requested threshold.
- `noSliverFaces(label: string, shape: ShapeLike, threshold?: number): void` — Check that a shape has no sliver faces below the requested score threshold.
- `noSelfIntersection(label: string, shape: ShapeLike): void` — Best-effort exact-shape validity guard for self-intersections or broken B-Rep topology.

### `Constraint`

- `makeParallel(builder: ConstrainedSketchBuilder, a: LineArg, b: LineArg): ConstrainedSketchBuilder` — Constrain two lines to be parallel.
- `enforceAngle(builder: ConstrainedSketchBuilder, a: LineArg, b: LineArg, angleDeg: number): ConstrainedSketchBuilder` — Constrain the signed angle from line `a` to line `b`.
- `horizontal(builder: ConstrainedSketchBuilder, line: LineArg): ConstrainedSketchBuilder` — Constrain a line to be horizontal.
- `vertical(builder: ConstrainedSketchBuilder, line: LineArg): ConstrainedSketchBuilder` — Constrain a line to be vertical.
- `equalLength(builder: ConstrainedSketchBuilder, a: LineArg, b: LineArg): ConstrainedSketchBuilder` — Constrain two lines to have equal length.
- `distance(builder: ConstrainedSketchBuilder, a: PointArg, b: PointArg, value: number): ConstrainedSketchBuilder` — Constrain the distance between two points.
- `fix(builder: ConstrainedSketchBuilder, pt: PointArg, x: number, y: number): ConstrainedSketchBuilder` — Fix a point at a specific coordinate.
- `coincident(builder: ConstrainedSketchBuilder, a: PointArg, b: PointArg): ConstrainedSketchBuilder` — Constrain two points to occupy the same location.
- `perpendicular(builder: ConstrainedSketchBuilder, a: LineArg, b: LineArg): ConstrainedSketchBuilder` — Constrain two lines to be perpendicular.
- `length(builder: ConstrainedSketchBuilder, line: LineArg, value: number): ConstrainedSketchBuilder` — Constrain the length of a line.

### `Points`

- `distance(a: Vec3, b: Vec3): number` — Euclidean distance between two 3D points.
- `midpoint(a: Vec3, b: Vec3): Vec3` — Center point between two 3D points.
- `lerp(a: Vec3, b: Vec3, t: number): Vec3` — Linearly interpolate between two 3D points. t=0 returns a, t=1 returns b.
- `direction(a: Vec3, b: Vec3): Vec3` — Unit direction vector from a to b. Throws if a and b are the same point.
- `offset(point: Vec3, dir: Vec3, amount: number): Vec3` — Move a point along a direction vector by a given amount.
- `polar(length: number, angleDeg: number, from?: [ number, number ]): [ number, number ]` — Compute a 2D point at distance and angle (degrees) from an optional origin.

### `connector`

Connector factory. Create attachment points: `connector({...})`, `connector.male(type, {...})`, etc.

---

<!-- guides/coordinate-system.md -->

# Coordinate System Convention

ForgeCAD uses a **Z-up** right-handed coordinate system.

## Axes

| Axis | Direction       | Positive |
|------|-----------------|----------|
| X    | Left / Right    | Right    |
| Y    | Forward / Back  | Forward  |
| Z    | Up / Down       | Up       |

## Standard Views

| View   | Camera position direction | Sees plane |
|--------|--------------------------|------------|
| Front  | −Y                       | XZ         |
| Back   | +Y                       | XZ         |
| Right  | +X                       | YZ         |
| Left   | −X                       | YZ         |
| Top    | +Z                       | XY         |
| Bottom | −Z                       | XY         |

## GizmoViewcube Face Mapping

Three.js BoxGeometry material indices vs ForgeCAD labels (Z-up remapping):

| Index | Three.js direction | ForgeCAD label |
|-------|--------------------|----------------|
| 0     | +X                 | Right          |
| 1     | −X                 | Left           |
| 2     | +Y                 | Front          |
| 3     | −Y                 | Back           |
| 4     | +Z                 | Top            |
| 5     | −Z                 | Bottom         |

Default drei labels are Y-up; ForgeCAD passes `faces={['Right','Left','Front','Back','Top','Bottom']}`.

## Grid

The ground plane is XY (Z = 0). Extrusion goes along +Z. Manifold is Y-up internally — if a kernel-facing operation behaves as if axes are swapped, check for Manifold Y-up semantics leaking through.

---

<!-- guides/geometry-conventions.md -->

# Geometry Conventions

ForgeCAD wraps Manifold (mesh kernel) and Three.js (Y-up renderer). This doc captures convention mismatches and how ForgeCAD resolves them.

## Winding Order

CCW = positive area, CW = empty in Manifold's `CrossSection`. ForgeCAD auto-fixes at all entry points:
- `polygon(points)` — computes signed area (shoelace), reverses if CW
- `path().close()` — same fix

**Rule for new code:** Any function accepting user point arrays that creates a `CrossSection` MUST auto-fix winding.

## Coordinate System (Z-up vs Y-up)

Three.js is Y-up; ForgeCAD is Z-up. Fix applied at camera level (`camera.up = (0,0,1)`) — geometry coordinates are native Z-up. Never swap Y/Z in geometry.

## Revolution Axis

`CrossSection.revolve()` revolves around Y. Profile X = radial distance, Profile Y = height (becomes Z after revolution). Profile must be at X > 0.

## Boolean Winding (3D)

Manifold requires consistent outward face normals. ForgeCAD only creates meshes through Manifold's own constructors, which guarantee correct normals.

## Transform Order

Transforms apply left-to-right. `Sketch.rotate()`, `scale()`, and `mirror()` operate around bounding-box center. For 3D `Shape` / `ShapeGroup`, `scale()` and `mirror()` operate around bounding-box center, while `rotate()` remains origin-based unless you pass `options.pivot` or use `rotateAroundAxis(...)`.

For explicit transform objects: `A.mul(B)` = apply A then B; `composeChain(A, B, C)` = A→B→C.

## Assembly Frame Composition

```ts
childWorld = composeChain(childBase, jointMotion, jointFrame, parentWorld)
```

Prefer `composeChain(...)` over manual `.mul(...).mul(...)` in kinematics code to avoid order mistakes.

## Summary

| Convention | User sees | Kernel needs | Where we fix it |
|---|---|---|---|
| Winding | Any point order | CCW | `polygon()`, `path().close()` |
| Up axis | Z-up | Y-up (Three.js) | `camera.up`, gizmo labels |
| Revolution | "revolve this profile" | Profile in X-Y, X>0 | Documented only |
| Face normals | Doesn't think about it | Outward-pointing | Manifold constructors |
| Transform order | Left-to-right chain | Post-multiply | Native match |

---

<!-- guides/positioning.md -->

# Positioning Strategy

## Rule 0: if parts should touch, use connectors first

For any fixed assembly where parts are meant to stay in contact in the final model, start with connectors + `matchTo()`. This applies to furniture, fixtures, toys, enclosures, sleds, and any other static multi-part object, not only mechanisms.

Use raw `translate()` and `rotate()` when parts are intentionally free-floating or when you are doing quick exploratory layout. Use `attachTo()` for rough bounding-box placement. But if the relationship is a real interface, make it explicit with connectors.

## Primitive origin convention

All 3D primitives are **centered on XY, base at Z=0**:

| Primitive | X range | Y range | Z range |
|-----------|---------|---------|---------|
| `box(60, 40, 20)` | [-30, 30] | [-20, 20] | [0, 20] |
| `cylinder(50, 10)` | [-10, 10] | [-10, 10] | [0, 50] |
| `sphere(15)` | [-15, 15] | [-15, 15] | [-15, 15] |
| `torus(20, 5)` | [-25, 25] | [-25, 25] | [-5, 5] |

Sphere and torus are fully centered (symmetric in Z). Box and cylinder sit on the XY ground plane — **Z goes up from zero, never negative**.

This means `box(w, d, h).translate(0, 0, -h / 2)` is the manual way to "center on Z" — it moves the box from `[0, h]` to `[-h / 2, h / 2]`. Prefer `box(w, d, h).placeReference('center', [0, 0, 0])` when you want full XYZ centering.

Do not assume `center: true` or a positional `true` gives OpenSCAD-style full XYZ centering. Primitive placement is fixed unless the primitive docs explicitly say otherwise.

---

Most positioning bugs come from manual coordinate arithmetic. Use these methods in priority order.

## 1. Connectors + `matchTo()` — default for mating interfaces

Define connectors on parts; `matchTo()` provides automatic 6-DOF alignment. The child translates and rotates so its connector aligns with the target's — origins coincide, axes oppose (plug-in model).

```javascript
const shelf = box(200, 120, 10).translate(0, 0, -5).withConnectors({
  left_tab: connector.male("dovetail", { origin: [-100, 0, 0], axis: [-1, 0, 0] }),
});
const panel = box(12, 120, 200).translate(0, 0, -100).withConnectors({
  shelf_0: connector.female("dovetail", { origin: [6, 0, -50], axis: [1, 0, 0] }),
});
const placed = shelf.matchTo(panel, "left_tab", "shelf_0");
// Dictionary form for multiple pairs on same target:
const placed2 = shelf.matchTo(panel, { left_tab: "shelf_0" });
// Named group children bubble connectors via dotted paths:
const cabinet = group({ name: "Left", shape: panel });
shelf.matchTo(cabinet, "left_tab", "Left.shelf_0");
```

**Why connectors first:** stable (don't shift on fillet/chamfer/boolean), semantic (carry type/gender), oriented (full frame), queryable (`shape.connectorDistance('a','b')`), explode-aware.

For a non-mechanism fixed-assembly example, see `examples/api/static-assembly-connectors.forge.js`.

## 2. `group()` — local coordinates for multi-part assemblies

The most common positioning bug: manually adding a parent's global offset to every sub-part. One wrong sign or forgotten variable and parts float into space. **Use `group()` to build parts in local coordinates (at the origin), then position the group once.**

```javascript
// BAD — every sub-part repeats the parent's global position
const unitY = -18, unitZ = 70;
const body = lib.roundedBox(100, 20, 32, 4).translate(0, unitY, unitZ);
const panel = box(98, 2, 18).translate(0, unitY - 12, unitZ + 4);
const louver = box(88, 2, 6).translate(0, unitY - 14, unitZ - 11);
const led = sphere(1.2).translate(35, unitY - 12, unitZ + 9);

// GOOD — build at local origin, group, translate once
const body = lib.roundedBox(100, 20, 32, 4);
const panel = box(98, 2, 18).translate(0, -12, 4);        // relative to local origin
const louver = box(88, 2, 6).translate(0, -14, -11);      // relative to local origin
const led = sphere(1.2).translate(35, -12, 9);             // relative to local origin
const indoorUnit = group(
  { name: 'Body', shape: body },
  { name: 'Panel', shape: panel },
  { name: 'Louver', shape: louver },
  { name: 'LED', shape: led },
).translate(0, -18, 70);  // ONE translate for the whole assembly
```

**Groups nest.** Build sub-assemblies as groups, then group those into larger assemblies — each level has its own local origin.

```javascript
const fan = group(hub, ...blades).translate(0, 25, 0);  // fan assembly
const outdoorUnit = group(
  { name: 'Body', shape: casing },
  { name: 'Fan', shape: fan },             // already a group
  { name: 'Grille', shape: grille },
).translate(0, 23, -42);                    // position the whole outdoor unit
```

**When to use something else:** `group()` preserves individual shapes — you can't boolean (subtract/intersect) a group. If a sub-part needs a boolean with the parent body, do that boolean first in local coordinates, then group the result.

## 3. `pointAlong()` — orient cylinders before positioning

```javascript
// BAD
const pipe = cylinder(100, 5).rotateX(90).translate(x, y, z);
// GOOD — reads as "pipe pointing along Y"
const pipe = cylinder(100, 5).pointAlong([0, 1, 0]).translate(x, y, z);
```

**Always call `pointAlong()` BEFORE `matchTo()` or `translate()`** — it reorients around the origin.

## 4. `attachTo()` — quick bounding-box positioning

```javascript
const column = cylinder(50, 8).attachTo(base, 'top', 'bottom');
```

`child.attachTo(parent, parentAnchor, selfAnchor, offset)`. Anchor points shift on fillet/chamfer/boolean — fragile for assembly interfaces, fine for quick prototyping.

## 5. `rotateAroundTo()` — aim a point around a hinge/axis

```javascript
const aimed = arm.rotateAroundTo([0, 0, 1], [0, 0, 0], "tip", [30, 30, 20]);
// Exact line solve:
const lineHit = arm.rotateAroundTo([0, 0, 1], [0, 0, 0], "tip", [30, 30, 0], { mode: 'line' });
```

## 6. `moveToLocal()` — offset from another shape's min corner

```javascript
const part = box(20, 20, 30).moveToLocal(base, 10, 10, 10);
```

## 7. `translate()` — for simple offsets or bridging computed locations

```javascript
const pipeLen = bb2.min[1] - bb1.max[1];
const pipe = cylinder(pipeLen, 5).pointAlong([0, 1, 0]).translate(40, (bb1.max[1] + bb2.min[1]) / 2, bb1.min[2] + 15);
```

## 8. `placeReference()` — align any anchor to a world coordinate

Place a shape so a named anchor point lands exactly where you want it. Accepts all built-in anchors (`'bottom'`, `'center'`, `'top-front-left'`, etc.) plus custom references from `withReferences()`.

```javascript
// Ground a shape — bottom face center at Z = 0
const grounded = shape.placeReference('bottom', [0, 0, 0])

// Center at the world origin
const centered = shape.placeReference('center', [0, 0, 0])

// Align left edge to X = 10
const aligned = shape.placeReference('left', [10, 0, 0])
```

Also works with custom placement references for cross-file parts:

```javascript
// widget.forge.js — define once
return union(base, post).withReferences({ points: { mount: [0, -16, -4] } });

// importer — consume
const widget = require("./widget.forge.js").placeReference("mount", [120, 40, 0]);
```

For cross-file parts needing proper alignment, prefer connectors over placement references.

---

<!-- generated/sketch.md -->

# Sketch API

2D geometry creation, transforms, booleans, constrained sketches, and extrusion.

## Contents

- [2D Sketch Primitives](#2d-sketch-primitives) — `path`, `stroke`, `rect`, `circle2d`, `roundedRect`, `polygon`, `ngon`, `ellipse`, `slot`, `arcSlot`, `star`
- [2D Sketch Booleans](#2d-sketch-booleans) — `union2d`, `difference2d`, `intersection2d`
- [2D Sketch Features](#2d-sketch-features) — `filletCorners`
- [Tracked Solid Edge Features](#tracked-solid-edge-features) — `filletTrackedEdge`, `chamferTrackedEdge`
- [2D Text](#2d-text) — `loadFont`, `text2d`, `textWidth`
- [Constrained Sketches](#constrained-sketches) — `constrainedSketch`, `addRect`, `addPolygon`, `addRegularPolygon`
- [2D Geometry Helpers](#2d-geometry-helpers) — `point`, `line`, `circle`, `degrees`, `radians`
- [Sketch](#sketch) — Transforms, Booleans, Features, Promotion, Placement, Labels, Measurement
- [ConstrainedSketchBuilder](#constrainedsketchbuilder) — Drawing, Entities, Geometric Constraints, Dimensional Constraints, Coincidence & Equality, Tangent Transitions, Shape Constraints, Positioning, Solving
- [ConstraintSketch](#constraintsketch)
- [SketchGroupBuilder](#sketchgroupbuilder)
- [Point2D](#point2d)
- [Line2D](#line2d)
- [Circle2D](#circle2d)
- [Rectangle2D](#rectangle2d)

## Functions

### 2D Sketch Primitives

#### `path()` — Create a new [`PathBuilder`](/docs/curves#pathbuilder) for tracing a 2D outline point by point.

[`PathBuilder`](/docs/curves#pathbuilder) is a fluent API for constructing 2D profiles using a mix of line segments, arcs, bezier curves, and splines. Always start with `.moveTo(x, y)` to set the starting point. Call `.close()` to get a filled `Sketch`, or `.stroke(width)` to thicken an open polyline into a solid profile.

Edge labels can be assigned with `.label('name')` after any segment — they propagate through extrusion, revolve, loft, and sweep into named faces on the resulting [`Shape`](/docs/core#shape).

```ts
// Closed triangle
const triangle = path().moveTo(0, 0).lineH(50).lineV(30).close();

// L-shaped bracket as a stroke
const bracket = path().moveTo(0, 0).lineH(50).lineV(-70).lineAngled(20, 235).stroke(4);

// Labeled edges for downstream face references
const slot = path()
  .moveTo(0, 0)
  .lineTo(30, 0).label('bottom')
  .lineTo(30, 10)
  .lineTo(0, 10).label('top')
  .close();
```

```ts
path(): PathBuilder
```

#### `stroke()` — Create a stroked polyline sketch from an array of 2D points.

```ts
stroke(points: [ number, number ][], width: number, join?: "Round" | "Square"): Sketch
```

#### `rect()` — Create a 2D rectangle centered at the origin.

```ts
rect(40, 20).extrude(5);
```

```ts
rect(width: number, height: number): Sketch
```

#### `circle2d()` — Create a 2D circle centered at the origin.

Omit `segments` for a smooth (auto-tessellated) circle. Pass an integer to get a regular polygon approximation — e.g. `6` for a hexagon, `8` for an octagon.

```ts
circle2d(25).extrude(10);          // smooth cylinder
circle2d(25, 6).extrude(10);       // hexagonal prism
```

```ts
circle2d(radius: number, segments?: number): Sketch
```

#### `roundedRect()` — Create a 2D rectangle with rounded corners, centered at the origin.

The corner radius is automatically clamped to `min(width/2, height/2)` so it can never exceed the shape dimensions.

```ts
roundedRect(60, 30, 5).extrude(3);
```

```ts
roundedRect(width: number, height: number, radius: number): Sketch
```

#### `polygon()` — Create a 2D polygon from an array of `[x, y]` points or `Point2D` objects.

Winding order is normalized automatically — clockwise (CW) input is silently reversed to CCW before being passed to the geometry kernel.

```ts
polygon([[0, 0], [50, 0], [25, 40]]).extrude(5); // triangle
```

```ts
polygon(points: ([ number, number ] | Point2D)[]): Sketch
```

#### `ngon()` — Create a regular polygon inscribed in a circle of the given radius.

`radius` is the center-to-vertex (circumradius) distance. Use `sides` of `3` for a triangle, `6` for a hexagon, etc. The first vertex is at the top (−90° from +X).

```ts
ngon(6, 20).extrude(10); // hexagonal prism, circumradius 20
```

```ts
ngon(sides: number, radius: number): Sketch
```

#### `ellipse()` — Create a 2D ellipse centered at the origin.

```ts
ellipse(30, 15).extrude(5);
ellipse(30, 15, 32).extrude(5); // lower-resolution approximation
```

```ts
ellipse(rx: number, ry: number, segments?: number): Sketch
```

#### `slot()` — Create a slot (oblong / stadium shape) — a rectangle with semicircular ends, centered at the origin.

```ts
slot(40, 10).extrude(3); // 40mm long, 10mm wide slot
```

```ts
slot(length: number, width: number): Sketch
```

#### `arcSlot()` — Create an arc-shaped slot (banana / annular sector) centered at the origin.

The slot is symmetric about the +X axis. The two ends are closed with semicircular caps. `pitchRadius` is the distance from the origin to the centerline of the slot, and `thickness` is the radial width of the slot.

```ts
arcSlot(135, 74, 40).extrude(5); // pitch R135, 74° sweep, 40mm wide
```

```ts
arcSlot(pitchRadius: number, sweepDeg: number, thickness: number): Sketch
```

#### `star()` — Create a star shape with alternating outer and inner radii.

```ts
star(5, 30, 12).extrude(4); // five-pointed star
```

```ts
star(points: number, outerR: number, innerR: number): Sketch
```

### 2D Sketch Booleans

#### `union2d()` — Combine 2D sketches into a single profile using an additive boolean union.

Accepts individual sketches or arrays: `union2d(a, b, c)` or `union2d([a, b, c])`. Uses Manifold's batch operation — faster than chaining `.add()` one by one when combining many sketches.

```ts
const cross = union2d(rect(60, 10), rect(10, 60));
```

```ts
union2d(...inputs: SketchOperandInput[]): Sketch
```

#### `difference2d()` — Subtract one or more 2D sketches from a base sketch.

The first sketch is the base; all subsequent sketches are subtracted from it. Accepts individual sketches or arrays: `difference2d(base, c1, c2)` or `difference2d([base, c1, c2])`. Uses Manifold's batch operation — faster than chaining `.subtract()` one by one.

```ts
const donut = difference2d(circle2d(50), circle2d(30));
```

```ts
difference2d(...inputs: SketchOperandInput[]): Sketch
```

#### `intersection2d()` — Keep only the area where all input sketches overlap (intersection boolean).

Accepts individual sketches or arrays: `intersection2d(a, b)` or `intersection2d([a, b, c])`. Uses Manifold's batch operation — faster than chaining `.intersect()` one by one.

```ts
const lens = intersection2d(circle2d(30).translate(-10, 0), circle2d(30).translate(10, 0));
```

```ts
intersection2d(...inputs: SketchOperandInput[]): Sketch
```

### 2D Sketch Features

#### `filletCorners()` — Create a polygon from points with specific corners rounded to arc fillets.

Each corner spec identifies a vertex by its index in the `points` array and the desired fillet `radius`. Both convex and concave corners are supported.

Constraints:

- Collinear corners cannot be filleted (throws an error)
- Two neighboring fillets whose tangent lengths overlap the same edge will throw
- Radius must be positive and small enough to fit within the adjacent edge lengths

Use `offset(-r).offset(+r)` instead if you want to round **all** convex corners uniformly. Use `filletCorners` when you need selective or mixed sharp/rounded profiles.

```ts
const roof = filletCorners(roofPoints, [
  { index: 3, radius: 19 },
  { index: 4, radius: 19 },
  { index: 5, radius: 19 },
]);
```

```ts
filletCorners(points: PointInput[], corners: FilletCornerSpec[]): Sketch
```

`FilletCornerSpec`: `{ index: number, radius: number, segments?: number }`

### Tracked Solid Edge Features

#### `filletTrackedEdge()` — Round a tracked vertical solid edge with a circular fillet.

Compiler-owned fillet for a narrow tracked-edge subset on solids.

This is **not** a general 2D sketch-corner fillet. It currently works only on tracked vertical edges from [`box()`](/docs/core#box) or `Rectangle2D` extrusions (plus rigid transforms and supported preserved descendants of those). Generic sketch extrudes, including `rect(...).extrude(...)`, are outside the supported subset right now.

**Supported edges:**

- Tracked vertical edges from [`box()`](/docs/core#box) or `Rectangle2D.extrude()`
- Rigid transforms between tracked source and target
- Untouched sibling tracked vertical edges after earlier `filletTrackedEdge`/`chamferTrackedEdge`

**Not supported:** edges after shell, hole, cut, trim, difference, intersection, generic sketch extrudes, or tapered extrudes.

Canonical quadrants: `vert-bl → [1,-1]`, `vert-br → [-1,-1]`, `vert-tr → [-1,1]`, `vert-tl → [1,1]`

```ts
const base = Rectangle2D.fromDimensions(0, 0, 50, 50).extrude(20);
const filleted = filletTrackedEdge(base, base.edge('vert-br'), 5, [-1, -1]);
```

```ts
filletTrackedEdge(shape: Shape, edge: EdgeRef, radius: number, quadrant?: [ number, number ], segments?: number): Shape
```

**`EdgeRef`**

| Option | Type | Description |
|--------|------|-------------|
| `start` | `[ number, number, number ]` | Start point |
| `end` | `[ number, number, number ]` | End point |
| `query?` | `EdgeQueryRef` | Compiler-owned edge query when available. |
| `curve?` | `EdgeCurve` | Exact or parametric curve family when the backend/source can identify one. |
| `faceName?` | `string` | Owning face name when the edge is associated with one face in a larger topology. |
| `name` | | — |

#### `chamferTrackedEdge()` — Bevel a tracked vertical solid edge with a 45° chamfer.

Compiler-owned chamfer for tracked vertical edges. Requires a compile-plan-covered target. This is not a general 2D sketch-corner tool; supported subset and quadrant semantics are the same as `filletTrackedEdge()` - see that function for details.

```ts
const base = Rectangle2D.fromDimensions(0, 0, 50, 50).extrude(20);
const chamfered = chamferTrackedEdge(base, base.edge('vert-br'), 3, [-1, -1]);
```

```ts
chamferTrackedEdge(shape: Shape, edge: EdgeRef, size: number, quadrant?: [ number, number ]): Shape
```

### 2D Text

#### `loadFont()` — Pre-load and cache a font for use with `text2d()`.

Fonts are cached by their source string (or `cacheKey` for `ArrayBuffer` sources), so repeated calls with the same path are free. Pre-loading is useful when you call `text2d()` many times with the same font — it avoids repeated disk reads.

Built-in font names that work everywhere (browser + CLI):

- `'sans-serif'` or `'inter'` — bundled Inter Regular

```ts
const font = loadFont('/path/to/Arial Bold.ttf');
text2d('Title', { size: 12, font }).extrude(1.5);
text2d('Subtitle', { size: 8, font }).extrude(1);
```

```ts
loadFont(source: string | ArrayBuffer, cacheKey?: string): opentype.Font
```

#### `text2d()` — Build a filled 2D Sketch from a text string.

The Sketch origin is at the left end of the text baseline by default. Use `align` and `baseline` options to adjust placement. Text is rendered using the bundled Inter font by default, or any TTF/OTF/WOFF font you provide.

`text2d()` creates real geometry. For temporary viewport annotations, prefer `Viewport.label()` so the text stays off the geometry and OCCT compile paths. Do not use either form of text to make unclear production geometry readable; model the physical artifact clearly instead.

Alignment reference table:

| `align`    | `baseline`   | Origin                              |
|------------|--------------|-------------------------------------|
| `'left'`   | `'baseline'` | Bottom-left of first char (default) |
| `'center'` | `'center'`   | Dead center of text block           |
| `'right'`  | `'top'`      | Top-right corner                    |

```ts
// Extruded nameplate
text2d('FORGE CAD', { size: 8 }).extrude(1.2);

// Centered label on the XY plane
text2d('V 2.0', { size: 6, align: 'center', baseline: 'center' });

// Engraved text cut into the top face of a box
const label = text2d('REV A', { size: 5, align: 'center', baseline: 'center' });
plate.subtract(label.onFace(plate, 'top', { protrude: -0.5 }).extrude(1));

// Custom TTF font
text2d('Hello', { size: 10, font: '/path/to/Arial.ttf' }).extrude(1);

// Pre-loaded font for reuse
const font = loadFont('/path/to/Arial Bold.ttf');
text2d('Title', { size: 12, font }).extrude(1.5);
```

```ts
text2d(content: string, options?: TextOptions): Sketch
```

**`TextOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `size?` | `number` | Cap height of the text in model units. All other dimensions (stroke weight, spacing) scale proportionally. |
| `letterSpacing?` | `number` | Extra space between characters in model units. Negative values tighten the tracking. |
| `align?` | `"left" \| "center" \| "right"` | Horizontal alignment relative to x = 0. - `'left'` — left edge at x = 0 (default) - `'center'` — centred on x = 0 - `'right'` — right edge at x = 0 |
| `baseline?` | `"baseline" \| "center" \| "top"` | Vertical alignment relative to y = 0. - `'baseline'` — y = 0 is the text baseline (bottom of capital letters) - `'center'` — y = 0 is the vertical midpoint of the cap height - `'top'` — y = 0 is the top of capital letters |
| `font?` | `string \| opentype.Font` | Font to use for text rendering. - `'sans-serif'` or `'inter'` — bundled Inter font (works everywhere, including browser) - **file path** — path to a TTF, OTF, or WOFF font file (CLI/Node only) - **Font object** — a previously loaded opentype.js Font (from `loadFont()`) - **omitted** — uses the bundled Inter font (same as `'sans-serif'`) |
| `flattenTolerance?` | `number` | Bezier flattening tolerance in model units. Smaller = more polygon segments = smoother curves. |

#### `textWidth()` — Measure the rendered advance width of a string without creating any geometry.

Uses the same font metrics as `text2d()`. Useful for computing layout dimensions before building the actual sketch — e.g. sizing a plate to fit a label.

```ts
const w = textWidth('SERIAL: 001', { size: 6 });
const plate = box(w + 10, 12, 2);
```

```ts
textWidth(content: string, options?: Pick<TextOptions, "size" | "letterSpacing" | "font">): number
```

### Constrained Sketches

#### `constrainedSketch()` — Create a parametric 2D sketch driven by geometric constraints and a nonlinear solver.

**Workflow**

1. Create a builder with `constrainedSketch()`.
2. Add geometry — points, lines, circles, arcs — using the builder methods.
3. Add constraints (`horizontal`, `length`, `fix`, etc.) to drive the geometry.
4. Call `.solve()` to run the solver and get a `ConstraintSketch` (which extends `Sketch`).

```ts
const sk = constrainedSketch();
const p1 = sk.point(0, 0);
const p2 = sk.point(50, 0);
const l1 = sk.line(p1, p2);
sk.fix(p1, 0, 0);
sk.horizontal(l1);
sk.length(l1, 50);
return sk.solve().extrude(10);
```

**Solver status**

```ts
const result = sk.solve();
result.constraintMeta.status;   // 'fully' | 'under' | 'over' | 'over-redundant'
result.constraintMeta.dof;      // 0 = fully constrained
result.constraintMeta.maxError; // residual — should be < 1e-6
result.inspect();               // human-readable summary
result.withUpdatedConstraint('cst-5', 120); // update a dimension without rebuilding
```

```ts
constrainedSketch(options?: ConstrainedSketchOptions): ConstrainedSketchBuilder
```

**`ConstrainedSketchOptions`**
- `strict?: boolean` — When true, adding a constraint that cannot be satisfied throws instead of silently discarding it.

#### `addRect()` — Add an axis-aligned rectangle concept to the builder.

Creates 4 vertices (CCW: bl→br→tr→tl), 4 sides, 4 structural constraints (`horizontal`/`vertical` on each side), CCW winding, a center point, a loop, and a shape. Returns a `ConstrainedRect` handle with 4 DOF (x, y, width, height).

Use `sk.rect()` as the shorthand builder method.

```ts
const sk = constrainedSketch();
const r = sk.rect({ x: 0, y: 0, width: 100, height: 50 });
sk.fix(r.bottomLeft, 0, 0);
sk.length(r.bottom, 120);  // override initial width
return sk.solve().extrude(10);
```

```ts
addRect(sk: ConstrainedSketchBuilder, options?: RectOptions): ConstrainedRect
```

**`RectOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `x?` | `number` | Bottom-left x coordinate. Default: 0. |
| `y?` | `number` | Bottom-left y coordinate. Default: 0. |
| `width?` | `number` | Width (along x). Default: 10. |
| `height?` | `number` | Height (along y). Default: 10. |
| `blockRotation?` | `boolean` | Prevent 180° rotation (ensures bottom edge points rightward). Default: false. |

**`ConstrainedRect`**

| Option | Type | Description |
|--------|------|-------------|
| `bottom` | `LineId` | bottom-left → bottom-right |
| `right` | `LineId` | bottom-right → top-right |
| `top` | `LineId` | top-right → top-left |
| `left` | `LineId` | top-left → bottom-left |
| `center` | `PointId` | Center point constrained to the geometric center via `midpoint` on the diagonal. Can be used in further constraints: `sk.fix(rect.center, 0, 0)`, `sk.coincident(rect.center, other)`. |
| `shape` | `ShapeId` | ShapeId for `shapeWidth`, `shapeHeight`, `shapeArea`, `shapeCentroidX/Y`. |
| `vertices` | `[ PointId, PointId, PointId, PointId ]` | CCW-ordered vertex array: [bottomLeft, bottomRight, topRight, topLeft]. |
| `sides` | `[ LineId, LineId, LineId, LineId ]` | CCW-ordered side array: [bottom, right, top, left]. |
| `bottomLeft`, `bottomRight`, `topRight`, `topLeft` | | — |

#### `addPolygon()` — Add a general polygon concept to the builder.

Creates n vertices and n sides (CCW: `sides[i]` from `vertices[i]` → `vertices[(i+1) % n]`). Applies a `ccw` constraint to enforce winding. All dimensional constraints (lengths, angles, position) are left to the caller.

Use `sk.addPolygon()` as the shorthand builder method.

```ts
const sk = constrainedSketch();
const tri = sk.addPolygon({ points: [[0,0],[100,0],[50,80]] });
sk.fix(tri.vertex(0), 0, 0);
sk.length(tri.side(0), 100);
return sk.solve().extrude(5);
```

```ts
addPolygon(sk: ConstrainedSketchBuilder, options: PolygonOptions): ConstrainedPolygon
```

**`PolygonOptions`**
- `points: ReadonlyArray<readonly [ number, number ]>` — Initial vertex coordinates. Minimum 3 points.
- `addLoop?: boolean` — Whether to register a closed loop for sketch generation. Default: true.
- `blockRotation?: boolean` — Prevent 180° rotation (ensures first edge maintains its initial direction). Default: false.

**`ConstrainedPolygon`**
- `vertices: PointId[]` — CCW-ordered PointIds.
- `sides: LineId[]` — CCW-ordered LineIds. `sides[i]` runs from `vertices[i]` → `vertices[(i+1) % n]`.
- `shape: ShapeId` — ShapeId for `shapeWidth`, `shapeHeight`, `shapeArea`, `shapeCentroidX/Y`.

#### `addRegularPolygon()` — Add a regular n-gon concept to the builder.

Vertices are placed at `(cx + r·cos(startAngle + i·2π/n), cy + r·sin(...))`. Equal-radius and equal-side constraints enforce regularity (4 DOF: center x/y, radius, rotation). The center point is tracked by the solver and exposed via the returned handle.

Use `sk.regularPolygon()` as the shorthand builder method.

```ts
const sk = constrainedSketch();
const hex = sk.regularPolygon({ sides: 6, radius: 25 });
sk.fix(hex.center, 0, 0);
sk.length(hex.side(0), 30);  // all sides change (equal constraint)
return sk.solve().extrude(5);
```

```ts
addRegularPolygon(sk: ConstrainedSketchBuilder, options: RegularPolygonOptions): ConstrainedRegularPolygon
```

**`RegularPolygonOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `sides` | `number` | Number of sides (minimum 3). |
| `radius?` | `number` | Circumradius — distance from center to vertex. Default: 10. |
| `cx?` | `number` | Center x coordinate. Default: 0. |
| `cy?` | `number` | Center y coordinate. Default: 0. |
| `startAngle?` | `number` | Angle (in degrees) of vertex[0] measured from the +X axis (CCW positive). Default: 0 (rightmost vertex). |
| `blockRotation?` | `boolean` | Prevent 180° rotation (ensures first edge maintains its initial direction). Default: false. |


**`ConstrainedRegularPolygon`** extends ConstrainedPolygon
- `center: PointId` — Center point. Use `sk.fix(poly.center, x, y)` to pin location, or `sk.coincident(poly.center, other)` to align with other geometry.

### 2D Geometry Helpers

#### `point()` — Create an analytic 2D point for measurement and construction geometry.

```ts
const p = point(10, 20);
p.distanceTo(point(30, 40));  // Euclidean distance
p.midpointTo(point(30, 40)); // midpoint
p.translate(5, 5);           // new shifted point
p.toTuple();                 // [10, 20]
```

```ts
point(x: number, y: number): Point2D
```

#### `line()` — Create an analytic 2D line segment between two points.

```ts
const l = line(0, 0, 50, 0);
l.length; l.midpoint; l.angle; l.direction;
l.parallel(10);          // parallel line offset 10 (positive = left)
l.intersect(l2);         // Point2D — treats lines as infinite
l.intersectSegment(l2);  // Point2D or null — segments only

Line2D.fromPointAndAngle(point(0, 0), 45, 100);
Line2D.fromPointAndDirection(point(0, 0), [1, 1], 50);
```

```ts
line(x1: number, y1: number, x2: number, y2: number): Line2D
```

#### `circle()` — Create an analytic 2D circle for measurement, construction, and extrusion.

```ts
const c = circle(0, 0, 25);
c.diameter; c.circumference; c.area;
c.pointAtAngle(90);  // Point2D at top (90° CCW from +X)

// Extrude to cylinder with named faces
const cyl = c.extrude(30);
cyl.face('top');   // FaceRef (planar)
cyl.face('side');  // FaceRef (curved)

Circle2D.fromDiameter(point(0, 0), 50);
```

```ts
circle(cx: number, cy: number, radius: number): Circle2D
```

#### `degrees()` — Identity function that returns degrees unchanged.

Use for clarity when the unit of an angle value would otherwise be ambiguous — e.g. `param("Angle", degrees(45))`.

```ts
degrees(deg: number): number
```

#### `radians()` — Convert radians to degrees.

ForgeCAD's public API uses degrees throughout. Use this when you have a radian value (e.g. from `Math.atan2`) that you want to express in degrees.

```ts
radians(rad: number): number
```

---

## Classes

### `Sketch`

Immutable 2D profile for extrusion, revolve, and other operations.

`Sketch` wraps Manifold's `CrossSection` with a chainable 2D API. Every method returns a new `Sketch` — the original is never mutated. Colors, edge labels, and placement data are preserved through all transforms and boolean operations.

Supported operations:

- **Transforms** — `translate`, `rotate`, `rotateAround`, `scale`, `mirror`
- **Booleans** — `add` (union), `subtract` (difference), `intersect`
- **Operations** — `offset`, `simplify`
- **Queries** — `area`, `bounds`, `isEmpty`, `numVert`
- **3D operations** — `extrude`, `revolve`, `onFace`
- **Regions** — `regions`, `region`
- **Placement** — `attachTo`

Named anchor positions used by `attachTo()`: `'center'` | `'top-left'` | `'top-right'` | `'bottom-left'` | `'bottom-right'` | `'top'` | `'bottom'` | `'left'` | `'right'`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `cross` | `ProfileBackend` | — |

**Transforms**

#### `translate()` — Move the sketch by the given X and Y offset.

```ts
translate(x: number, y?: number): Sketch
```

#### `rotate()` — Rotate the sketch around its bounding-box center.

```ts
rotate(degrees: number): Sketch
```

#### `rotateAround()` — Rotate the sketch around a specific pivot point.

```ts
rect(20, 20).rotateAround(45, [0, 0]);
```

```ts
rotateAround(degrees: number, pivot: [ number, number ]): Sketch
```

#### `scale()` — Scale the sketch relative to its bounding-box center.

Pass a single number for uniform scaling, or `[sx, sy]` for per-axis scaling.

```ts
scale(v: number | [ number, number ]): Sketch
```

#### `scaleAround()` — Scale the sketch relative to an arbitrary pivot point.

```ts
scaleAround(pivot: [ number, number ], v: number | [ number, number ]): Sketch
```

#### `mirror()` — Mirror the sketch across a line through its bounding-box center.

`normal` is the normal vector of the mirror line (not the line direction). For example, `[1, 0]` mirrors across a vertical line (Y axis direction), and `[0, 1]` mirrors across a horizontal line.

```ts
mirror(normal: [ number, number ]): Sketch
```

#### `mirrorThrough()` — Mirror the sketch across a line defined by a point and a normal direction.

```ts
mirrorThrough(point: [ number, number ], normal: [ number, number ]): Sketch
```

**Booleans**

#### `add()` — Add (union) one or more sketches to this sketch.

Accepts individual sketches or arrays: `sketch.add(a, b)` or `sketch.add([a, b])`. For combining many sketches at once, prefer the free function `union2d()` which uses Manifold's batch operation and is faster than chaining.

```ts
circle2d(20).add(rect(10, 30)).extrude(5);
```

```ts
add(...others: SketchOperandInput[]): Sketch
```

#### `subtract()` — Subtract one or more sketches from this sketch.

Accepts individual sketches or arrays: `sketch.subtract(a, b)` or `sketch.subtract([a, b])`. For subtracting many cutters at once, prefer the free function `difference2d()`.

```ts
rect(40, 40).subtract(circle2d(10)).extrude(5);
```

```ts
subtract(...others: SketchOperandInput[]): Sketch
```

#### `intersect()` — Intersect this sketch with one or more others (keep overlapping area only).

Accepts individual sketches or arrays: `sketch.intersect(a, b)` or `sketch.intersect([a, b])`. For intersecting many sketches, prefer the free function `intersection2d()`.

```ts
intersect(...others: SketchOperandInput[]): Sketch
```

**Features**

#### `offset()` — Inflate (positive delta) or deflate (negative delta) the sketch contour.

Use `offset(-r).offset(+r)` to round every convex corner of a closed sketch.

- `'Round'` — smooth arc at each corner (default)
- `'Square'` — flat mitered extension
- `'Miter'` — sharp pointed extension

```ts
rect(40, 20).offset(3);            // expand by 3
rect(40, 20).offset(-2).offset(2); // round all convex corners
```

```ts
offset(delta: number, join?: "Square" | "Round" | "Miter"): Sketch
```

#### `regions()` — Decompose this sketch into its distinct filled regions, sorted largest-first by area.

A single sketch can contain several disconnected filled areas (e.g., two separate rectangles, or a ring shape with a hole). This method enumerates all top-level connected regions as independent `Sketch` objects, each with its own outer boundary and associated holes.

```ts
const pair = union2d(rect(40, 40), rect(40, 40).translate(60, 0));
const [left, right] = pair.regions(); // largest first
left.extrude(5);
```

```ts
regions(): Sketch[]
```

#### `region()` — Select the single filled region that contains the given 2D seed point.

The seed must lie strictly inside the filled area — not on a boundary edge and not inside a hole. Throws a descriptive error if the seed is outside all regions. If unsure where regions are, use `.regions()` first — each result has `.bounds()`.

```ts
const donut = circle2d(50).subtract(circle2d(30));
donut.region([40, 0]).extrude(10); // seed at radius 40, inside the ring
```

```ts
region(seed: [ number, number ]): Sketch
```

**Promotion**

#### `extrude()` — Extrude this 2D sketch along Z to create a 3D solid. Supports twist and scale tapering.

```ts
extrude(height: number, opts?: { twist?: number; divisions?: number; scaleTop?: number | [ number, number ]; }): Shape
```

#### `revolve()` — Revolve this 2D sketch around the Y axis to create a 3D solid of revolution.

```ts
revolve(degrees?: number, segments?: number): Shape
```

**Placement**

#### `attachTo()` — Position this sketch relative to another using named anchor points.

Computes the translation needed to align `selfAnchor` on this sketch with `targetAnchor` on the target sketch, then applies an optional pixel-exact offset.

Anchor positions: `'center'` | `'top-left'` | `'top-right'` | `'bottom-left'` | `'bottom-right'` | `'top'` | `'bottom'` | `'left'` | `'right'`

```ts
const arm = rect(4, 70).attachTo(plate, 'bottom-left', 'top-left');
const shifted = rect(4, 70).attachTo(plate, 'bottom-left', 'top-left', [5, 0]);
```

```ts
attachTo(target: Sketch, targetAnchor: Anchor, selfAnchor?: Anchor, offset?: [ number, number ]): Sketch
```

#### `onFace()` — Place this sketch on a face or planar target in 3D space.

Use this when a 2D profile should be oriented onto a 3D face before extrusion or other downstream operations.

```ts
onFace(parentOrFace: Shape | { toShape(): Shape; } | { _bbox(): { min: number[]; max: number[]; }; } | FaceRef, faceOrOpts?: "front" | "back" | "left" | "right" | "top" | "bottom" | string | FaceRef | { u?: number; v?: number; protrude?: number; selfAnchor?: Anchor; }, opts?: { u?: number; v?: number; protrude?: number; selfAnchor?: Anchor; }): Sketch
```

**Labels**

#### `labelEdge()` — Label the single boundary edge (for circles, single-loop profiles). Returns a new sketch.

```ts
labelEdge(name: string): Sketch
```

#### `labelEdges()` — Label edges in winding order, or by named map for rect.

Positional: `labelEdges('bottom', 'right', 'top', 'left')` — one per edge, `null` to skip. Named (rect only): `labelEdges({ bottom: 'floor', top: 'ceiling' })`. Returns a new sketch.

```ts
labelEdges(...args: (string | null)[] | [ Record<string, string> ]): Sketch
```

#### `edgeLabels()` — List current edge label names.

```ts
edgeLabels(): string[]
```

#### `prefixLabels()` — Prefix all edge labels. Returns a new sketch with prefixed labels.

```ts
prefixLabels(prefix: string): Sketch
```

#### `renameLabel()` — Rename a single edge label. Returns a new sketch.

```ts
renameLabel(from: string, to: string): Sketch
```

#### `dropLabels()` — Remove specific labels. Returns a new sketch.

```ts
dropLabels(...names: string[]): Sketch
```

#### `dropAllLabels()` — Remove all labels. Returns a new sketch.

```ts
dropAllLabels(): Sketch
```

**Measurement**

#### `area()` — Return the total filled area of the sketch.

```ts
area(): number
```

#### `bounds()` — Return the axis-aligned bounding box of the sketch.

```ts
bounds(): ProfileBounds
```

#### `isEmpty()` — Return `true` if the sketch contains no filled area.

```ts
isEmpty(): boolean
```

#### `numVert()` — Return the number of vertices in the polygon representation of the sketch contours.

```ts
numVert(): number
```

#### `toPolygons()` — Return the sketch as a list of polygons matching its contour topology.

Useful when you need raw polygon data for inspection or custom export.

```ts
toPolygons(): number[][][]
```

**Other**

#### `color()` — Set the display color of this sketch.

Color is preserved through all transforms and boolean operations. Pass `undefined` to clear the color.

```ts
circle2d(20).color('#ff0000').extrude(5);
```

```ts
color(value: string | undefined): Sketch
```

#### `clone()` — Create an explicit copy of this sketch for branching variants.

Because all Sketch operations are immutable, `clone()` is rarely needed. Use it when you want to assign the same sketch to multiple names and continue modifying each independently without confusion.

```ts
clone(): Sketch
```

### `ConstrainedSketchBuilder`

**Drawing**

#### `moveTo()` — Move the cursor to `(x, y)` and start a new profile loop.

```ts
moveTo(x: number, y: number): this
```

#### `lineTo()` — Draw a line from the current cursor to `(x, y)`.

```ts
lineTo(x: number, y: number): this
```

#### `lineH()` — Draw a horizontal line of length `dx` from the current cursor.

```ts
lineH(dx: number): this
```

#### `lineV()` — Draw a vertical line of length `dy` from the current cursor.

```ts
lineV(dy: number): this
```

#### `lineAngled()` — Draw a line of the given `length` at `degrees` from +X.

```ts
lineAngled(length: number, degrees: number): this
```

#### `arcTo()` — Draw a circular arc from the current cursor to `(x, y)` with the given radius.

```ts
arcTo(x: number, y: number, radius: number, clockwise?: boolean): this
```

#### `arcByCenter()` — Create an arc from an explicit center point and endpoint IDs.

```ts
arcByCenter(centerId: PointId, startId: PointId, endId: PointId, clockwise?: boolean, name?: string, fixedRadius?: boolean): ArcId
```

#### `bezier()` — Create a cubic Bezier curve from four control points.

```ts
bezier(p0: any, p1: any, p2: any, p3: any, name?: string): BezierId
```

#### `bezierTo()` — Draw a cubic Bezier from the current cursor to `(x3, y3)`.

```ts
bezierTo(x1: number, y1: number, x2: number, y2: number, x3: number, y3: number): this
```

#### `blendTo()` — Draw a smooth Bezier tangent to the previous arc.

```ts
blendTo(x: number, y: number, weight?: number): this
```

#### `label()` — Label the current path segment.

```ts
label(name: string): this
```

#### `close()` — Close the current path and register the loop.

```ts
close(): this
```

#### `addLoopCircle()` — Add a circle loop to the path.

```ts
addLoopCircle(center: PointId, radius: number, segments?: number): this
```

#### `addLoop()` — Add a closed polygon loop from point IDs.

```ts
addLoop(points: any[]): this
```

#### `addProfileLoop()` — Add a profile loop from prebuilt line/arc/bezier segments.

```ts
addProfileLoop(segments: Array<{ kind: "line"; line: any; } | { kind: "arc"; arc: any; } | { kind: "bezier"; bezier: any; }>): this
```

**Entities**

#### `point()` — Add a free point to the sketch at `(x, y)`.

If `x` or `y` are omitted, the point is placed at the bounding-box center of existing geometry so it starts near other entities rather than at the origin. Throws if either coordinate is `NaN` or `Infinity`.

```ts
point(x?: number, y?: number, fixed?: boolean): PointId
```

#### `pointAt()` — Return the `PointId` of the point created at the given insertion index.

```ts
pointAt(index: number): PointId
```

#### `line()` — Connect two existing points with a line segment.

Pass `construction = true` for a helper line that participates in constraints but is excluded from the solved sketch output (not part of any profile loop).

```ts
const axis = sk.line(sk.point(0, -50), sk.point(0, 50), true);
sk.symmetric(p1, p2, axis);
```

```ts
line(a: PointId, b: PointId, construction?: boolean, name?: string): LineId
```

#### `lineAt()` — Return the `LineId` of the line created at the given insertion index.

```ts
lineAt(index: number): LineId
```

#### `circle()` — Add a circle to the sketch with the given center point and initial radius.

The radius is a starting value — if you add a `radius()` or `diameter()` constraint, the solver will adjust it. Non-construction circles automatically register a loop.

```ts
circle(center: PointId, radius: number, construction?: boolean, segments?: number, name?: string): CircleId
```

#### `circleAt()` — Return the `CircleId` of the circle created at the given insertion index.

```ts
circleAt(index: number): CircleId
```

#### `shape()` — Register a named shape (closed polygon) from an ordered list of line IDs.

The `ShapeId` can be passed to `shapeWidth()`, `shapeHeight()`, `shapeArea()`, `shapeCentroidX()`, `shapeCentroidY()`, and `shapeEqualCentroid()` constraints. Shape registration is done automatically by concept factories like `rect()` and `addPolygon()`.

```ts
shape(lines: LineId[]): ShapeId
```

#### [`group()`](/docs/core#group) — Create a rigid-body group with a local coordinate frame.

Points and lines added to the group move together as a unit — the solver sees 3 DOF (x, y, θ) instead of 2N per point. After configuring the group, call `.done()` to register it and receive a `SketchGroupHandle`.

Group points are addressable by their `PointId` in all sketch constraints (e.g. `sk.coincident`, `sk.distance`) just like any other points.

```ts
const g = sk.group({ x: 50, y: 30 });
const p0 = g.point(0, 0);    // local origin → world (50, 30)
const p1 = g.point(100, 0);  // local (100,0) → world (150, 30)
const l = g.line(p0, p1);
g.fixRotation();
const handle = g.done();
// p0, p1 work in constraints like any other PointId:
sk.coincident(p0, someExternalPoint);
```

```ts
group(opts?: { x?: number; y?: number; theta?: number; id?: string; }): SketchGroupBuilder
```

#### `rect()` — Add an axis-aligned rectangle concept. Returns a `ConstrainedRect` handle with named vertices, sides, and center.

```ts
rect(options?: RectOptions): ConstrainedRect
```

#### `addPolygon()` — Add a general polygon concept (CCW winding enforced). Returns a `ConstrainedPolygon` handle.

```ts
addPolygon(options: PolygonOptions): ConstrainedPolygon
```

#### `regularPolygon()` — Add a regular n-gon concept (equal sides, CCW winding). Returns a `ConstrainedRegularPolygon` handle with a center point.

```ts
regularPolygon(options: RegularPolygonOptions): ConstrainedRegularPolygon
```

#### `groupRect()` — Add a rigid rectangle as a group concept. Returns a `ConstrainedGroupRect` handle with named vertices and sides. The rectangle is fixed in shape — only position (and optionally rotation) varies.

```ts
groupRect(options: GroupRectOptions): ConstrainedGroupRect
```

**Geometric Constraints**

#### `horizontal()` — Constrain a line to be horizontal (parallel to the X axis).

```ts
horizontal(line: any): this
```

#### `vertical()` — Constrain a line to be vertical (parallel to the Y axis).

```ts
vertical(line: any): this
```

#### `parallel()` — Constrain two lines to be parallel.

```ts
parallel(a: any, b: any): this
```

#### `sameDirection()` — Constrain two lines to point in the same direction.

```ts
sameDirection(a: any, b: any): this
```

#### `oppositeDirection()` — Constrain two lines to point in opposite directions.

```ts
oppositeDirection(a: any, b: any): this
```

#### `perpendicular()` — Constrain two lines to be perpendicular.

```ts
perpendicular(a: any, b: any): this
```

#### `tangent()` — Constrain a line/circle or circle/circle tangency relationship.

```ts
tangent(a: any, b: any): this
```

#### `collinear()` — Constrain a point to lie on the infinite extension of a line.

```ts
collinear(point: any, line: any): this
```

#### `symmetric()` — Constrain two points to be symmetric about an axis line.

```ts
symmetric(a: any, b: any, axis: any): this
```

#### `blockRotation()` — Prevent 180° rotation of a polygon by anchoring its first edge.

```ts
blockRotation(points: any[], axis?: "x" | "y"): this
```

**Dimensional Constraints**

#### `distance()` — Constrain the Euclidean distance between two points.

```ts
distance(a: any, b: any, value: number): this
```

#### `length()` — Constrain the length of a line segment.

```ts
length(line: any, value: number): this
```

#### `angle()` — Constrain the signed angle from line `a` to line `b`.

```ts
angle(a: any, b: any, value: number): this
```

#### `radius()` — Constrain the radius of a circle.

```ts
radius(circle: any, value: number): this
```

#### `diameter()` — Constrain the diameter of a circle.

```ts
diameter(circle: any, value: number): this
```

#### `hDistance()` — Constrain the horizontal distance between two points.

```ts
hDistance(a: any, b: any, value: number): this
```

#### `vDistance()` — Constrain the vertical distance between two points.

```ts
vDistance(a: any, b: any, value: number): this
```

#### `pointLineDistance()` — Constrain the signed perpendicular distance from a point to a line.

```ts
pointLineDistance(point: any, line: any, value: number): this
```

#### `lineDistance()` — Constrain the perpendicular offset distance between two lines.

```ts
lineDistance(a: any, b: any, value: number): this
```

#### `absoluteAngle()` — Constrain the absolute angle of a line measured from +X.

```ts
absoluteAngle(line: any, value: number): this
```

#### `arcLength()` — Constrain the arc length of an arc.

```ts
arcLength(arc: any, value: number): this
```

#### `equalRadius()` — Constrain two circles to have equal radii.

```ts
equalRadius(a: any, b: any): this
```

#### `angleBetween()` — Constrain the unsigned angle between two lines.

```ts
angleBetween(a: any, b: any, value: number): this
```

**Coincidence & Equality**

#### `equal()` — Constrain two lines to have equal length.

```ts
equal(a: any, b: any): this
```

#### `coincident()` — Constrain two points to coincide.

```ts
coincident(a: any, b: any): this
```

#### `concentric()` — Constrain two circles to share a center.

```ts
concentric(a: any, b: any): this
```

#### `fix()` — Pin a point at a specific world location.

```ts
fix(point: any, x?: number, y?: number): this
```

#### `midpoint()` — Constrain a point to lie at the midpoint of a line.

```ts
midpoint(point: any, line: any): this
```

#### `pointOnCircle()` — Constrain a point to lie on the perimeter of a circle.

```ts
pointOnCircle(point: any, circle: any): this
```

#### `pointOnLine()` — Constrain a point to lie on the bounded segment of a line.

```ts
pointOnLine(point: any, line: any): this
```

#### `ccw()` — Constrain all given points to be in counter-clockwise order.

```ts
ccw(...points: any[]): this
```

**Tangent Transitions**

#### `lineTangentArc()` — Constrain a line to be tangent to an arc at its start or end point.

```ts
lineTangentArc(line: any, arc: any, atStart: boolean): this
```

#### `arcTangentArc()` — Constrain two arcs to be tangent at their shared junction point.

```ts
arcTangentArc(arcA: any, arcB: any, aAtStart?: boolean, bAtStart?: boolean): this
```

#### `bezierTangentArc()` — Constrain a Bezier to be tangent to an arc at one endpoint.

```ts
bezierTangentArc(bezier: any, arc: any, atBezierStart: boolean, atArcStart: boolean): this
```

#### `smoothBlend()` — Create a Bezier blend between two arcs.

```ts
smoothBlend(arc1: any, arc2: any, options?: { weight?: number; arc1End?: "start" | "end"; arc2End?: "start" | "end"; }): BezierId
```

**Shape Constraints**

#### `shapeWidth()` — Constrain a shape's width.

```ts
shapeWidth(shape: any, value: number): this
```

#### `shapeHeight()` — Constrain a shape's height.

```ts
shapeHeight(shape: any, value: number): this
```

#### `shapeCentroidX()` — Constrain a shape's centroid X position.

```ts
shapeCentroidX(shape: any, value: number): this
```

#### `shapeCentroidY()` — Constrain a shape's centroid Y position.

```ts
shapeCentroidY(shape: any, value: number): this
```

#### `shapeArea()` — Constrain a shape's area.

```ts
shapeArea(shape: any, value: number): this
```

#### `shapeEqualCentroid()` — Constrain two shapes to have the same centroid.

```ts
shapeEqualCentroid(a: any, b: any): this
```

**Positioning**

#### `offsetX()` — Constrain the horizontal (X-axis) offset between two lines. Uses the start-point of each line to measure horizontal distance. `value` is the signed distance: b.startPt.x − a.startPt.x = value.

```ts
offsetX(a: any, b: any, value: number): this
```

#### `offsetY()` — Constrain the vertical (Y-axis) offset between two lines. Uses the start-point of each line to measure vertical distance. `value` is the signed distance: b.startPt.y − a.startPt.y = value.

```ts
offsetY(a: any, b: any, value: number): this
```

#### `importPoint()` — Import a `Point2D` object into the sketch.

```ts
importPoint(pt: { x: number; y: number; }, fixed?: boolean): PointId
```

#### `importLine()` — Import a `Line2D` object into the sketch.

```ts
importLine(l: { start: { x: number; y: number; }; end: { x: number; y: number; }; }, fixed?: boolean): LineId
```

#### `importRectangle()` — Import a `Rectangle2D` as four points and four lines.

```ts
importRectangle(r: { vertices: [ { x: number; y: number; }, { x: number; y: number; }, { x: number; y: number; }, { x: number; y: number; } ]; }, fixed?: boolean): { ... }
```

#### `referencePoint()` — Add a fixed reference point at `(x, y)`.

```ts
referencePoint(x: number, y: number): PointId
```

#### `referenceLine()` — Add a fixed reference line from `(x1, y1)` to `(x2, y2)`.

```ts
referenceLine(x1: number, y1: number, x2: number, y2: number): LineId
```

#### `referenceFrom()` — Import a single named entity from a solved sketch as fixed reference geometry.

```ts
referenceFrom(source: ConstraintSketch, entityId: string): PointId | LineId | null
```

#### `referenceAllFrom()` — Import all non-construction entities from a solved sketch as fixed references.

```ts
referenceAllFrom(source: ConstraintSketch): { points: Map<string, PointId>; lines: Map<string, LineId>; }
```

**Solving**

#### `constrain()` — Add a raw constraint object to the builder.

```ts
constrain(constraint: Omit<SketchConstraint, "id">): this
```

#### `solve()` — Run the constraint solver and return a solved sketch.

The returned `ConstraintSketch` extends `Sketch` and can be used directly in all 3D operations (`extrude`, `revolve`, etc.). It also exposes `constraintMeta` with the solver status:

```ts
const result = sk.solve();
result.constraintMeta.status;   // 'fully' | 'under' | 'over' | 'over-redundant'
result.constraintMeta.dof;      // 0 = fully constrained
result.constraintMeta.maxError; // residual — should be < 1e-6
result.inspect();               // human-readable summary
result.withUpdatedConstraint('cst-5', 120); // update a dimension without rebuilding
```

**Troubleshooting**

- **Under-constrained (dof > 0)** — add `fix()`, `length()`, or other dimensional constraints.
- **Over-constrained** — conflicting constraints are auto-rejected. Check `result.constraintMeta.constraints` and `result.inspect()`.
- **maxError > 1e-6** — solver did not converge; check for contradictory constraints.

```ts
solve(options?: SolveOptions): ConstraintSketch | Sketch
```

#### `solveConstraintsOnly()` — Run the solver without building a full `ConstraintSketch`.

Lighter than `solve()` — skips profile and DOF analysis. Useful for lightweight constraint validation or progress monitoring mid-construction.

```ts
solveConstraintsOnly(options?: SolveOptions): { maxError: number; rejectedCount: number; definition: ConstraintDefinition; }
```

#### `route()` — Start a directional route from coordinates.

Returns a [`RouteBuilder`](/docs/viewport#routebuilder) - describe the path with up/down/left/right/arcLeft/arcRight. Each method returns the entity ID (`LineId` or `ArcId`) for use in `sk.*` constraints.

```js
const r = sk.route(0, 0);
const stem = r.up(18);
r.arcLeft(8.9);
const neck = r.down();
r.done();
sk.offsetX(stem, neck, 10.8);
```

```ts
route(x: number, y: number): RouteBuilder
```

### `ConstraintSketch`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `constraintMeta` | `SketchConstraintMeta` | — |
| `definition` | `ConstraintDefinition` | — |

**Methods:**

#### `detectArrangement()` — Enumerate all bounded regions formed by the line arrangement of this sketch. Construction lines are excluded. Regions are returned largest-first by area.

```ts
detectArrangement(): Sketch[]
```

#### `detectArrangementRegion()` — Select the single arrangement region that contains the given seed point. Throws if no region contains the seed.

```ts
detectArrangementRegion(_seed: [ number, number ]): Sketch
```

#### `toPolyline()` — Return the solved constrained path as a sampled 2D polyline.

Use this when a construction rail was authored with `constrainedSketch()` and should feed another operation such as `Loft.pathOnXz(...)`. The sketch must contain exactly one profile path.

```ts
toPolyline(samples?: number): [ number, number ][]
```

#### `withUpdatedConstraint()` — Re-solve the sketch after changing the value of one existing constraint.

Use this for interactive dimension edits without rebuilding the whole sketch graph. It attempts a warm-started solve first, then falls back to a full solve if needed.

```ts
withUpdatedConstraint(constraintId: string, value: number): ConstraintSketch
```

#### `inspect()` — Return a human-readable diagnostic string of the solved state.

```ts
inspect(): string
```

### `SketchGroupBuilder`

#### `point()` — Add a point in local coordinates. Returns its globally-addressable PointId.

```ts
point(lx: number, ly: number): PointId
```

#### `line()` — Connect two group points with a line. Both must be PointIds from this group.

```ts
line(a: PointId, b: PointId, name?: string): LineId
```

#### `fixRotation()` — Freeze rotation (theta). Group can still translate - 2 DOF remain.

```ts
fixRotation(): this
```

#### `fix()` — Freeze all 3 DOF - group is completely fixed.

```ts
fix(): this
```

#### `done()` — Finalize and register the group with the builder.

```ts
done(): SketchGroupHandle
```

### `Point2D`

An immutable 2D point with measurement and construction helpers.

Used as construction geometry in sketches, constraints, and analytic measurements. All methods return new instances — `Point2D` is immutable.

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `x` | `number` | — |
| `y` | `number` | — |

**Methods:**

#### `distanceTo()` — Measure straight-line distance to another point.

```ts
distanceTo(other: Point2D): number
```

#### `midpointTo()` — Compute the midpoint between this point and another point.

```ts
midpointTo(other: Point2D): Point2D
```

#### `translate()` — Return a point shifted by the given delta.

```ts
translate(dx: number, dy: number): Point2D
```

#### `toTuple()` — Convert this point to a plain `[x, y]` tuple.

```ts
toTuple(): [ number, number ]
```

### `Line2D`

An immutable 2D line segment with length, angle, intersection, and parallel helpers.

Provides both segment-only (`intersectSegment`) and infinite-line (`intersect`) intersection queries. All methods return new instances.

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `start` | `Point2D` | — |
| `end` | `Point2D` | — |

**Methods:**

#### `length()` — Length of the line segment.

```ts
get length(): number
```

#### `midpoint()` — Midpoint of the line segment.

```ts
get midpoint(): Point2D
```

#### `angle()` — Direction angle in degrees, measured CCW from +X.

```ts
get angle(): number
```

#### `direction()` — Unit direction vector from start to end.

```ts
get direction(): [ number, number ]
```

#### `parallel()` — Create a parallel line offset by the given distance.

Positive distance shifts to the left of the line direction.

```ts
parallel(distance: number): Line2D
```

#### `intersect()` — Intersect this line with another infinite line.

```ts
intersect(other: Line2D): Point2D | null
```

#### `intersectSegment()` — Intersect this line with another as bounded segments.

```ts
intersectSegment(other: Line2D): Point2D | null
```

#### `fromCoordinates()` — Create a line from raw coordinates.

```ts
static fromCoordinates(x1: number, y1: number, x2: number, y2: number): Line2D
```

#### `fromPointAndAngle()` — Create a line from a start point, angle, and length.

```ts
static fromPointAndAngle(origin: Point2D, angleDeg: number, length: number): Line2D
```

#### `fromPointAndDirection()` — Create a line from a start point, direction vector, and length.

```ts
static fromPointAndDirection(origin: Point2D, dir: [ number, number ], length: number): Line2D
```

### `Circle2D`

An immutable 2D circle with area, circumference, and extrusion support.

Extruding a `Circle2D` produces a cylinder with named `top`, `bottom`, and `side` faces accessible via the topology API.

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `center` | `Point2D` | — |
| `radius` | `number` | — |

**Methods:**

#### `diameter()` — Diameter of the circle.

```ts
get diameter(): number
```

#### `circumference()` — Circumference of the circle.

```ts
get circumference(): number
```

#### `area()` — Area of the circle.

```ts
get area(): number
```

#### `pointAtAngle()` — Return a point on the circle at the given angle.

```ts
pointAtAngle(angleDeg: number): Point2D
```

#### `translate()` — Return a translated circle.

```ts
translate(dx: number, dy: number): Circle2D
```

#### `toSketch()` — Convert this circle to a sketch profile.

```ts
toSketch(segments?: number): Sketch
```

#### `extrude()` — Extrude the circle into a solid cylinder.

```ts
extrude(height: number, segments?: number): Shape
```

#### `fromCenterAndRadius()` — Create a circle from its center and radius.

```ts
static fromCenterAndRadius(center: Point2D, radius: number): Circle2D
```

#### `fromDiameter()` — Create a circle from its center and diameter.

```ts
static fromDiameter(center: Point2D, diameter: number): Circle2D
```

### `Rectangle2D`

A rectangle with named sides, vertices, and extrusion support.

Sides are named based on the rectangle's local orientation at construction time. Vertices go: bottom-left, bottom-right, top-right, top-left (CCW).

Use `rect()` for the normal centered sketch primitive. Use `Rectangle2D` when you need named sides/vertices, or an extrusion with tracked vertical edges such as `vert-br` for `filletTrackedEdge()` / `chamferTrackedEdge()`.

Extruding a `Rectangle2D` produces a [`Shape`](/docs/core#shape) with named faces: `top`, `bottom`, `side-left`, `side-right`, `side-top`, `side-bottom`. These are accessible via the topology API (`.face()`, `.edge()`).

```ts
const r = Rectangle2D.fromDimensions(0, 0, 100, 60);
r.side('top'); r.side('left');     // Line2D
r.vertex('top-left');              // Point2D
r.width; r.height; r.center;
const [d1, d2] = r.diagonals();   // [bl-tr, br-tl]

r.toSketch();      // Sketch (for 2D operations)
r.extrude(20);     // Shape with named faces

Rectangle2D.fromCenterAndDimensions(point(50, 30), 100, 60);
Rectangle2D.from2Corners(point(0, 0), point(100, 60));
Rectangle2D.from3Points(p1, p2, p3);  // free-angle rectangle
```

#### `width()` — Width of the rectangle.

```ts
get width(): number
```

#### `height()` — Height of the rectangle.

```ts
get height(): number
```

#### `center()` — Geometric center of the rectangle.

```ts
get center(): Point2D
```

#### `side()` — Return a named side of the rectangle.

```ts
side(name: RectSide): Line2D
```

#### `sideAt()` — Return a side by index.

```ts
sideAt(index: number): Line2D
```

#### `vertex()` — Return a named vertex of the rectangle.

```ts
vertex(name: RectVertex): Point2D
```

#### `diagonals()` — Return the two diagonals of the rectangle.

```ts
diagonals(): [ Line2D, Line2D ]
```

#### `toSketch()` — Convert the rectangle to a sketch profile.

```ts
toSketch(): Sketch
```

#### `translate()` — Return a translated rectangle.

```ts
translate(dx: number, dy: number): Rectangle2D
```

#### `fromDimensions()` — Create an axis-aligned rectangle from origin corner plus width and height.

```ts
static fromDimensions(x: number, y: number, width: number, height: number): Rectangle2D
```

#### `fromCenterAndDimensions()` — Create a rectangle centered on a point.

```ts
static fromCenterAndDimensions(center: Point2D, width: number, height: number): Rectangle2D
```

#### `from2Corners()` — Create an axis-aligned rectangle from two opposite corners.

```ts
static from2Corners(p1: Point2D, p2: Point2D): Rectangle2D
```

#### `from3Points()` — Create a free-angle rectangle from three points.

`p1` and `p2` define one edge, and `p3` chooses the perpendicular side.

```ts
static from3Points(p1: Point2D, p2: Point2D, p3: Point2D): Rectangle2D
```

#### `extrude()` — Extrude the rectangle into a solid prism with named topology.

```ts
extrude(height: number, up?: boolean): Shape
```

---

<!-- generated/curves.md -->

# Curves & Surfacing

Smooth curves, lofted surfaces, swept solids, splines, and high-level product skins.

## Contents

- [Curves & Surfacing](#curves-surfacing) — `Loft.station`, `Loft.leftRail`, `Loft.rightRail`, `Loft.frontRail`, `Loft.backRail`, `Loft.centerRail`, `Loft.pathOnXz`, `Loft.pathOnYz`, `Loft.pathOnXy`, `Loft.withGuideRails`, `hermiteTransitionG2`, `nurbs3d`, `spline2d`, `spline3d`, `loft`, `loftAlongSpine`, `sweep`, `variableSweep`, `nurbsSurface`, `surfacePatch`, `transitionCurve`, `transitionSurface`, `connectEdges`
- [Surface Members](#surface-members) — `surfaceBand`, `SurfaceBody`
- [Curve3D](#curve3d)
- [NurbsCurve3D](#nurbscurve3d)
- [NurbsSurface](#nurbssurface)
- [PathBuilder](#pathbuilder) — Line Segments, Arcs, Curves, Closing & Output
- [HermiteCurve3D](#hermitecurve3d)
- [QuinticHermiteCurve3D](#quintichermitecurve3d)
- [ProductSkin](#productskin)
- [ProductSurfaceRef](#productsurfaceref)
- [ProductSurfaceBuilder](#productsurfacebuilder)
- [ProductSkinBuilder](#productskinbuilder)
- [ProductStationBuilder](#productstationbuilder)
- [ProductPanelBuilder](#productpanelbuilder)
- [ProductRibbonBuilder](#productribbonbuilder)
- [ProductSpoutBuilder](#productspoutbuilder)
- [ProductHandleBuilder](#producthandlebuilder)
- [ProductHandleFeature](#producthandlefeature)
- [CylinderCarrier](#cylindercarrier)
- [PlaneCarrier](#planecarrier)
- [ProductSkinCarrier](#productskincarrier)
- [SurfacePath](#surfacepath)
- [SurfacePathBuilder](#surfacepathbuilder)
- [SurfaceBand](#surfaceband)
- [SurfaceBodyBuilder](#surfacebodybuilder)
- [SurfaceMemberBuilder](#surfacememberbuilder)
- [SurfaceJoinBuilder](#surfacejoinbuilder)
- [CounterboreBuilder](#counterborebuilder)
- [RoundedSlotBuilder](#roundedslotbuilder)
- [Surface](#surface)
- [Blend](#blend)
- [Analysis](#analysis)
- [Product](#product)
- [Carrier](#carrier)
- [SurfaceMembers](#surfacemembers)
- [Slot](#slot)
- [Counterbore](#counterbore)
- [Ribs](#ribs)

## Functions

### Curves & Surfacing

#### `Loft.station()` — Create a loft station from a 2D profile and an axis position.

```ts
Loft.station(profile: Sketch, position: number): LoftStation
```

`LoftStation`: `{ profile: Sketch, position: number }`

#### `Loft.leftRail()` — Create a guide rail that constrains the section-local negative-X side.

```ts
Loft.leftRail(path: LoftGuideRailPath): LoftGuideRail
```

`LoftGuideRail`: `{ side: LoftGuideRailSide, path: LoftGuideRailPath }`

#### `Loft.rightRail()` — Create a guide rail that constrains the section-local positive-X side.

```ts
Loft.rightRail(path: LoftGuideRailPath): LoftGuideRail
```

#### `Loft.frontRail()` — Create a guide rail that constrains the section-local positive-Y side.

```ts
Loft.frontRail(path: LoftGuideRailPath): LoftGuideRail
```

#### `Loft.backRail()` — Create a guide rail that constrains the section-local negative-Y side.

```ts
Loft.backRail(path: LoftGuideRailPath): LoftGuideRail
```

#### `Loft.centerRail()` — Create a guide rail that moves section centers along the loft.

```ts
Loft.centerRail(path: LoftGuideRailPath): LoftGuideRail
```

#### `Loft.pathOnXz()` — Place a 2D guide path onto the XZ plane.

The path's first coordinate becomes X and its second coordinate becomes Z. Use this for left/right silhouette rails authored with [`path()`](/docs/sketch#path) or [`constrainedSketch()`](/docs/sketch#constrainedsketch).

```ts
Loft.pathOnXz(path: LoftPath2D, y?: number): Vec3[]
```

#### `Loft.pathOnYz()` — Place a 2D guide path onto the YZ plane.

The path's first coordinate becomes Y and its second coordinate becomes Z. Use this for front/back crown rails authored with [`path()`](/docs/sketch#path) or [`constrainedSketch()`](/docs/sketch#constrainedsketch).

```ts
Loft.pathOnYz(path: LoftPath2D, x?: number): Vec3[]
```

#### `Loft.pathOnXy()` — Place a 2D guide path onto the XY plane.

The path's first coordinate becomes X and its second coordinate becomes Y. Use this when lofting along X or Y and a rail lives in a horizontal sketch plane.

```ts
Loft.pathOnXy(path: LoftPath2D, z?: number): Vec3[]
```

#### `Loft.withGuideRails()` — Loft through profile stations while forcing generated sections to follow guide rails.

Stations define the cross-section family. Guide rails define the side or center paths the loft must pass through. With opposite side rails, the section is scaled to touch both rails. With one side rail, the section keeps its interpolated size unless a center rail is also present.

```ts
Loft.withGuideRails(stations: LoftStation[], rails: LoftGuideRail[], options?: LoftWithGuideRailsOptions): Shape
```

**`LoftOptions`**
- `edgeLength?: number` — Marching-grid edge length for level-set meshing. Smaller = finer.
- `boundsPadding?: number` — Optional extra bounds padding.

**`LoftWithGuideRailsOptions`** extends LoftOptions
- `axis?: LoftAxis` — Primary station axis. Default Z.
- `samples?: number` — Number of generated loft stations including ends. Default scales with station count.
- `railSamples?: number` — Number of points sampled from curve-backed rails before axis interpolation. Default 64.

#### `hermiteTransitionG2()` — Create a quintic Hermite transition curve between two edge endpoints (G2 continuity).

The curve starts at `a.point` tangent to `a.tangent` with curvature `a.curvature`, and ends at `b.point` tangent to `b.tangent` with curvature `b.curvature`, with smooth G2-continuous interpolation matching position, tangent, and curvature.

```ts
hermiteTransitionG2(a: QuinticHermiteCurveEndpoint, b: QuinticHermiteCurveEndpoint): QuinticHermiteCurve3D
```

**`QuinticHermiteCurveEndpoint`**

| Option | Type | Description |
|--------|------|-------------|
| `point` | `Vec3` | Position |
| `tangent` | `Vec3` | Tangent direction (will be normalized internally) |
| `curvature?` | `Vec3` | Second derivative / curvature vector. Default [0, 0, 0]. |
| `weight?` | `number` | Weight: scales tangent magnitude relative to chord length. Default 1.0. |

#### `nurbs3d()` — Create a NURBS curve from control points.

With default options, creates a cubic non-rational B-spline with uniform clamped knots. Set `weights` for rational curves (exact circles, conics). Set `degree` for linear (1), quadratic (2), cubic (3), or higher-order curves.

```js
// Simple cubic B-spline through control points
const curve = nurbs3d([[0,0,0], [10,5,0], [20,-5,10], [30,0,5]]);
const tube = sweep(circle(2), curve);
```

```js
// Rational quadratic — exact circular arc
const arc = nurbs3d(
  [[10,0,0], [10,10,0], [0,10,0]],
  { degree: 2, weights: [1, Math.SQRT1_2, 1] }
);
```

```ts
nurbs3d(points: Vec3[], options?: NurbsCurve3DOptions): NurbsCurve3D
```

**`NurbsCurve3DOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `degree?` | `number` | Polynomial degree (default 3 = cubic). Must be ≥ 1. |
| `weights?` | `number[]` | Rational weights, one per control point (default: all 1.0 = non-rational). |
| `knots?` | `number[]` | Knot vector (default: uniform clamped). Must have length = controlPoints.length + degree + 1. |
| `closed?` | `boolean` | Whether the curve is closed/periodic (default false). |

#### `spline2d()` — Build a smooth Catmull-Rom spline sketch from 2D control points.

A closed spline (default) returns a filled profile. An open spline requires a strokeWidth option to produce a solid sketch. Use tension (0..1, default 0.5) to control curve tightness.

```ts
spline2d(points: Vec2[], options?: Spline2DOptions): Sketch
```

**`Spline2DOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `closed?` | `boolean` | Closed loop (default true). |
| `tension?` | `number` | Catmull-Rom tension in [0, 1]. 0 = very round, 1 = linear-ish. Default 0.5. |
| `samplesPerSegment?` | `number` | Samples per segment (minimum 3). Default 16. |
| `strokeWidth?` | `number` | For open splines, provide stroke width to return a solid Sketch. If omitted for open splines, an error is thrown. |
| `join?` | `"Round" \| "Square"` | Stroke join for open splines. Default 'Round'. |

#### `spline3d()` — Create a reusable 3D spline curve object (Catmull-Rom).

The returned Curve3D provides sample(), pointAt(t), tangentAt(t), and length() for downstream use in sweep() or manual path operations.

```ts
spline3d(points: Vec3[], options?: Spline3DOptions): Curve3D
```

**`Spline3DOptions`**
- `closed?: boolean` — Closed loop (default false).
- `tension?: number` — Catmull-Rom tension in [0, 1]. 0 = very round, 1 = linear-ish. Default 0.5.

#### `loft()` — Loft between multiple sketches along Z stations.

Profiles can differ in topology and vertex count: interpolation is done on signed-distance fields and meshed with level-set extraction. Heights must be strictly increasing. Compatible loft stacks can also stay on the maintained export-backend path.

Performance note: loft is significantly heavier than primitive/extrude/revolve. If the part is axis-symmetric (bottles, vases, knobs), prefer revolve().

```ts
loft(profiles: Sketch[], heights: number[], options?: LoftOptions): Shape
```

#### `loftAlongSpine()` — Loft between multiple profiles positioned along an arbitrary 3D spine curve.

Unlike loft() which only supports Z heights, loftAlongSpine() places each profile at a position along a 3D spine, oriented perpendicular to the spine tangent. This enables lofting along curved paths — e.g., a wing root-to-tip transition that follows a swept-back leading edge.

The tValues array specifies where each profile sits along the spine (0 = start, 1 = end). Must have the same length as profiles and be in [0, 1].

Internally uses variableSweep infrastructure with SDF interpolation.

Performance note: uses level-set meshing, heavier than simple loft().

```ts
loftAlongSpine(profiles: Sketch[], spine: Curve3D | Vec3[], tValues: number[], options?: LoftAlongSpineOptions): Shape
```

**`LoftAlongSpineOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `samples?` | `number` | Number of samples when spine is a Curve3D. Default 48. |
| `edgeLength?` | `number` | Marching-grid edge length for level-set meshing. Smaller = finer. |
| `boundsPadding?` | `number` | Optional extra bounds padding. |
| `up?` | `Vec3` | Preferred "up" vector for local profile frame. Auto fallback is used near parallel segments. |

#### `sweep()`

```ts
sweep(profile: Sketch, path: SweepPathInput, options?: SweepOptions): Shape
```

**`SweepOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `samples?` | `number` | Number of samples when path is a Curve3D. Default 48. |
| `edgeLength?` | `number` | Marching-grid edge length for level-set meshing. Smaller = finer. |
| `boundsPadding?` | `number` | Optional extra bounds padding. |
| `up?` | `Vec3` | Preferred "up" vector for local profile frame. Auto fallback is used near parallel segments. |

#### `variableSweep()` — Sweep a variable cross-section along a 3D spine curve.

Unlike sweep(), which uses a single constant profile, variableSweep() interpolates between multiple profiles at different stations along the spine. This enables organic shapes like tapering tubes, bone-like structures, and sculptural forms.

Each section specifies a t parameter (0 = start, 1 = end of spine) and a 2D profile sketch. The SDF-based level-set mesher smoothly blends between profiles at intermediate positions.

Performance note: like sweep(), this uses level-set meshing internally.

```ts
variableSweep(spine: SweepPathInput, sections: VariableSweepSection[], options?: VariableSweepOptions): Shape
```

**`VariableSweepSection`**
- `t: number` — Parameter along the spine (0 = start, 1 = end).
- `profile: Sketch` — Cross-section profile at this station.

**`VariableSweepOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `samples?` | `number` | Number of samples when spine is a Curve3D. Default 48. |
| `edgeLength?` | `number` | Marching-grid edge length for level-set meshing. Smaller = finer. |
| `boundsPadding?` | `number` | Optional extra bounds padding. |
| `up?` | `Vec3` | Preferred "up" vector for local profile frame. Auto fallback is used near parallel segments. |

#### `nurbsSurface()` — Create a NURBS surface from a grid of control points.

The control grid is indexed as `controlGrid[u][v]` — each row is a curve in the V direction, and columns trace curves in the U direction.

With default options, creates a bicubic non-rational B-spline surface with uniform clamped knots.

```js
// Simple 4×4 control grid — a gently curved surface
const grid = [
  [[0,0,0], [10,0,2], [20,0,2], [30,0,0]],
  [[0,10,1], [10,10,5], [20,10,5], [30,10,1]],
  [[0,20,1], [10,20,5], [20,20,5], [30,20,1]],
  [[0,30,0], [10,30,2], [20,30,2], [30,30,0]],
];
const surface = nurbsSurface(grid, { thickness: 2 });
```

```ts
nurbsSurface(controlGrid: Vec3[][], options?: NurbsSurfaceOptions): Shape
```

**`NurbsSurfaceOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `degreeU?` | `number` | Degree in U direction (default 3). |
| `degreeV?` | `number` | Degree in V direction (default 3). |
| `weights?` | `number[][]` | Weights grid — same dimensions as controlGrid (default: all 1.0). |
| `knotsU?` | `number[]` | Knot vector in U direction (default: uniform clamped). |
| `knotsV?` | `number[]` | Knot vector in V direction (default: uniform clamped). |
| `thickness?` | `number` | Sheet thickness — if > 0, thickens the surface into a solid (default 0 = surface only). |
| `resolution?` | `number` | Tessellation resolution — points per direction (default 32). |
| `domain?` | `SurfaceDomainOptions` | Optional rectangular parameter domain in normalized [0, 1] U/V space. |
| `trim?` | `SurfaceTrimOptions` | Optional polygonal or NURBS-curve UV trim loops. Truck and OCCT support open trimmed surfaces; Manifold supports sampled thickened trimmed solids. |
| `tessellation?` | `SurfaceTessellationOptions` | Optional Truck kernel tessellation controls for render mesh generation. |
| `approximate?` | `boolean` | Explicit opt-in for sampled approximation paths on non-exact backends. |

**`SurfaceDomainOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `uMin?` | `number` | Lower U parameter bound in normalized surface space (default 0). |
| `uMax?` | `number` | Upper U parameter bound in normalized surface space (default 1). |
| `vMin?` | `number` | Lower V parameter bound in normalized surface space (default 0). |
| `vMax?` | `number` | Upper V parameter bound in normalized surface space (default 1). |

**`SurfaceTrimOptions`**
- `outer: SurfaceTrimLoopInput` — Outer trim loop in normalized post-domain UV space.
- `holes?: SurfaceTrimLoopInput[]` — Optional hole loops in normalized post-domain UV space.

**`SurfaceTessellationOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `mode?` | `"uniform" \| "adaptive"` | `uniform` uses resolution directly; `adaptive` lets the Truck kernel refine open sheets from chord error. |
| `tolerance?` | `number` | Target chord-error tolerance in model units for adaptive Truck tessellation. |
| `minResolution?` | `number` | Minimum adaptive samples per direction. |
| `maxResolution?` | `number` | Maximum adaptive samples per direction. Defaults to `resolution` when omitted. |

#### `surfacePatch()` — Create a smooth surface patch from 4 boundary curves (Coons patch).

The four curves form the boundary of a quadrilateral patch:

- bottom: u=0..1 at v=0 (from corner00 to corner10)
- top: u=0..1 at v=1 (from corner01 to corner11)
- left: v=0..1 at u=0 (from corner00 to corner01)
- right: v=0..1 at u=1 (from corner10 to corner11)

The interior is filled using bilinear Coons patch interpolation: P(u,v) = Lc(u,v) + Ld(u,v) - B(u,v)

The result is a thin solid created by offsetting the surface mesh along its normals by the specified thickness.

Note: curves should meet at corners. Small gaps are tolerated.

```ts
surfacePatch(curves: { ... }, options?: SurfacePatchOptions): Shape
```

**`SurfacePatchOptions`**
- `resolution?: number` — Number of samples along each direction. Default 24.
- `thickness?: number` — Thickness of the generated solid. Default 0 for an open exact sheet.
- `approximate?: boolean` — Allow explicit approximation for non-exact curve inputs such as Curve3D samples.

#### `transitionCurve()` — Create a smooth transition curve between two edges.

Returns a `HermiteCurve3D` that starts at `edgeA.point` tangent to `edgeA.tangent` and ends at `edgeB.point` tangent to `edgeB.tangent`.

The curve maintains G1 continuity (matching tangent direction) at both endpoints. Weight parameters control the shape of the transition.

```js
// Connect two edges with a balanced transition
const curve = transitionCurve(
  { point: [0, 0, 0], tangent: [1, 0, 0] },
  { point: [10, 5, 0], tangent: [1, 0, 0] },
);
```

// Weighted: curve hugs edge A longer const weighted = transitionCurve( { point: [0, 0, 0], tangent: [1, 0, 0] }, { point: [10, 5, 0], tangent: [1, 0, 0] }, { weightA: 2.0, weightB: 0.5 }, );

```

```ts
transitionCurve(edgeA: TransitionEdge, edgeB: TransitionEdge, options?: TransitionCurveOptions): HermiteCurve3D
```

**`TransitionEdge`**
- `point: Vec3` — Connection point on the edge. Can be any point along the edge where the transition should connect.
- `tangent: Vec3` — Tangent direction at the connection point. This is the direction the curve should initially follow when leaving this edge. For a straight edge, this is typically the edge direction pointing "outward" (away from the body of the edge, toward the other edge).
- `normal?: Vec3` — Surface normal at the connection point (optional). Used as a hint for the sweep frame's up vector.

**`TransitionCurveOptions`**
- `weightA?: number` — Weight for the start edge. Controls tangent magnitude at the start. - 1.0 (default): balanced transition - > 1.0: curve follows start edge longer before turning - < 1.0: curve turns sooner at the start
- `weightB?: number` — Weight for the end edge. Controls tangent magnitude at the end. - 1.0 (default): balanced transition - > 1.0: curve follows end edge longer before turning - < 1.0: curve turns sooner at the end
- `samples?: number` — Number of sample points for the output polyline. Default 64. Higher values give smoother curves at the cost of more geometry.

#### `transitionSurface()` — Create a solid transition surface between two edges by sweeping a profile along a Hermite transition curve.

This produces a watertight solid that smoothly connects the two edges. Works with both Manifold and OCCT backends.

```js
// Circular tube connecting two edges
const tube = transitionSurface(
  { point: [0, 0, 0], tangent: [1, 0, 0] },
  { point: [10, 5, 3], tangent: [0, 1, 0] },
  { radius: 0.5 },
);
```

// Custom profile with weights const custom = transitionSurface( { point: [0, 0, 0], tangent: [1, 0, 0] }, { point: [10, 5, 3], tangent: [0, 1, 0] }, { profile: mySketch, weightA: 1.5, weightB: 0.8 }, );

```

```ts
transitionSurface(edgeA: TransitionEdge, edgeB: TransitionEdge, options?: TransitionSurfaceOptions): Shape
```


**`TransitionSurfaceOptions`** extends TransitionCurveOptions

| Option | Type | Description |
|--------|------|-------------|
| `profile?` | `Sketch` | Cross-section profile to sweep along the transition curve. If omitted, a circular profile with `radius` is used. |
| `radius?` | `number` | Radius of circular cross-section (used when `profile` is omitted). Default: 5% of chord length. |
| `rectangleSection?` | `{ width: number; height: number; }` | Width and height for rectangular cross-section. Alternative to `radius` when `profile` is omitted. |
| `up?` | `Vec3` | Preferred up vector for the sweep frame. Default: auto-detected. |
| `edgeLength?` | `number` | Edge length for level-set meshing. Smaller = finer. |
| `boundsPadding?` | `number` | Extra bounds padding for level-set meshing. |

#### `connectEdges()` — Create a transition surface or solid bridge between two edge segments.

Tangents can be inferred from neighboring geometry or supplied explicitly through `options`. This is useful for loft-like blends where you want a direct connection between two edge spans.

```ts
connectEdges(edgeA: EdgeSegment, edgeB: EdgeSegment, options?: ConnectEdgesOptions): Shape
```

**`EdgeSegment`**

| Option | Type | Description |
|--------|------|-------------|
| `index` | `number` | Stable index within the extraction (deterministic for a given mesh). |
| `direction` | `Vec3` | Normalized direction from start → end. |
| `dihedralAngle` | `number` | Dihedral angle in degrees (0 = coplanar, 180 = knife edge). |
| `convex` | `boolean` | true = outside corner (convex), false = inside corner (concave). |
| `normalA` | `Vec3` | Normal of first adjacent face. |
| `normalB` | `Vec3` | Normal of second adjacent face (same as normalA for boundary edges). |
| `boundary` | `boolean` | true if this is a boundary (unmatched) edge — unusual for closed solids. |
| `start`, `end`, `midpoint`, `length` | | — |


**`ConnectEdgesOptions`** extends TransitionSurfaceOptions

| Option | Type | Description |
|--------|------|-------------|
| `endA?` | `EdgeEnd` | Which end of edge A to connect. Default: 'start'. |
| `endB?` | `EdgeEnd` | Which end of edge B to connect. Default: 'start'. |
| `tangentModeA?` | `TangentMode` | Tangent mode for edge A. Default: 'along'. |
| `tangentModeB?` | `TangentMode` | Tangent mode for edge B. Default: 'along'. |
| `tangentA?` | `Vec3` | Explicit tangent for edge A. |
| `tangentB?` | `Vec3` | Explicit tangent for edge B. |
| `flipA?` | `boolean` | Flip tangent A. |
| `flipB?` | `boolean` | Flip tangent B. |

### Surface Members

#### `surfaceBand()`

```ts
surfaceBand<C extends SurfaceCoordinate>(path: SurfacePath<C> | SurfacePathBuilder<C>, width: WidthProfile, cap?: SurfaceBandCap): SurfaceBand<C>
```

#### `SurfaceBody()` — Start a surface-member body builder for straps, inlays, guards, braces, cuffs, and similar physical members that live on a carrier surface.

```js
const carrier = Carrier.cylinder('guard-envelope').diameter(84).height(36).clearance(2);
const guard = SurfaceBody('simple-guard')
  .carrier(carrier)
  .member('left-strut')
  .band()
  .path(carrier.path().from({ angle: -132, z: 6 }).to({ angle: -58, z: 18 }))
  .section({ width: 5.5, thickness: 2.8, edgeRadius: 0.6 })
  .member('right-strut')
  .mirrorOf('left-strut')
  .member('front-hoop')
  .band()
  .path(carrier.path().around({ z: 18, fromAngle: -58, toAngle: 58 }))
  .section({ width: 6.2, thickness: 3, edgeRadius: 0.7 })
  .join('left-strut', 'front-hoop').blend({ radius: 3.2 })
  .join('right-strut', 'front-hoop').blend({ radius: 3.2 })
  .build();
```

```ts
SurfaceBody(name: string): SurfaceBodyBuilder
```

---

## Classes

### `Curve3D`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `points` | `Vec3[]` | — |
| `closed` | `boolean` | — |
| `tension` | `number` | — |

**Methods:**

#### `sampleBySegment()` — Sample the curve with a fixed number of points per segment.

```ts
sampleBySegment(samplesPerSegment?: number): Vec3[]
```

#### `sample()` — Sample the curve to an approximate total point count.

```ts
sample(count?: number): Vec3[]
```

#### `pointAt()` — Return the position on the curve at normalized parameter `t` in `[0, 1]`. O(1), no allocations.

```ts
pointAt(t: number): Vec3
```

#### `tangentAt()` — Return a unit tangent vector at normalized parameter `t` in `[0, 1]`. O(1), analytical derivative.

```ts
tangentAt(t: number): Vec3
```

#### `length()` — Approximate the curve length by polyline sampling.

```ts
length(samples?: number): number
```

### `NurbsCurve3D`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `controlPoints` | `Vec3[]` | — |
| `weights` | `number[]` | — |
| `knots` | `number[]` | — |
| `degree` | `number` | — |
| `closed` | `boolean` | — |

**Methods:**

#### `pointAt()` — Evaluate the curve at parameter t ∈ [0, 1]. Uses De Boor's algorithm — exact, O(degree²).

```ts
pointAt(t: number): Vec3
```

#### `tangentAt()` — Evaluate the unit tangent vector at parameter t ∈ [0, 1].

```ts
tangentAt(t: number): Vec3
```

#### `sample()` — Sample the curve uniformly at `count` points.

```ts
sample(count?: number): Vec3[]
```

#### `sampleAdaptive()` — Sample with adaptive density — more points in high-curvature regions.

```ts
sampleAdaptive(minCount?: number, maxCount?: number): Vec3[]
```

#### `length()` — Approximate arc length by summing polyline segment lengths.

```ts
length(samples?: number): number
```

#### `toPolyline()` — Convert to a format compatible with sweep() path input.

```ts
toPolyline(samples?: number): Vec3[]
```

### `NurbsSurface`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `controlGrid` | `Vec3[][]` | — |
| `weightsGrid` | `number[][]` | — |
| `knotsU` | `number[]` | — |
| `knotsV` | `number[]` | — |
| `degreeU` | `number` | — |
| `degreeV` | `number` | — |
| `nU` | `number` | — |
| `nV` | `number` | — |
| `domain` | `SurfaceDomainCompilePlan` | — |

**Methods:**

#### `pointAt()` — Evaluate the surface at parameters (u, v) ∈ [0, 1]². Uses tensor product evaluation: evaluate basis functions in U and V independently.

```ts
pointAt(u: number, v: number): Vec3
```

#### `normalAt()` — Evaluate the surface normal at (u, v) via cross product of partial derivatives.

```ts
normalAt(u: number, v: number): Vec3
```

#### `tessellate()` — Tessellate the surface into a triangle mesh. Returns positions, normals, and triangle indices.

```ts
tessellate(resU?: number, resV?: number): { positions: Vec3[]; normals: Vec3[]; indices: number[]; }
```

### `PathBuilder`

**Line Segments**

#### `moveTo()` — Move the cursor to an absolute position without drawing a segment.

When called after the initial [`path()`](/docs/sketch#path), this establishes the start of the outline. Calling `moveTo` again mid-path starts a new sub-path (hole in `close()`, separate segment for [`stroke()`](/docs/sketch#stroke)).

```ts
moveTo(x: number, y: number): this
```

#### `lineTo()` — Draw a straight line from the current cursor to an absolute position.

```ts
lineTo(x: number, y: number): this
```

#### `lineH()` — Draw a horizontal line segment by `dx` units from the current cursor.

Positive `dx` moves right; negative moves left.

```ts
lineH(dx: number): this
```

#### `lineV()` — Draw a vertical line segment by `dy` units from the current cursor.

Positive `dy` moves up; negative moves down.

```ts
lineV(dy: number): this
```

#### `lineAngled()` — Draw a line at the given angle and length from the current cursor.

Angle convention: `0°` points right (+X), `90°` points up (+Y).

```ts
// L-bracket with angled return
path().moveTo(0, 0).lineH(50).lineV(-70).lineAngled(20, 235).stroke(4);
```

```ts
lineAngled(length: number, degrees: number): this
```

**Arcs**

#### `arc()` — Draw an arc defined by center, radius, and angle range (no trig needed). If the path has no segments yet, automatically moves to the arc start. Positive sweep (startDeg < endDeg) = CCW, negative = CW.

```js
// Arc centered at (10, 0), radius 50, from -30° to +30°
path().arc(10, 0, 50, -30, 30).stroke(8, 'Round')
```

```ts
arc(cx: number, cy: number, radius: number, startDeg: number, endDeg: number): this
```

#### `arcTo()` — Draw a circular arc from the current position to (x, y) with the given radius. `clockwise=true` → arc curves to the right of the start→end direction. `clockwise=false` → arc curves to the left of the start→end direction.

```ts
arcTo(x: number, y: number, radius: number, clockwise?: boolean): this
```

#### `tangentArcTo()` — G1-continuous arc — radius derived from current tangent + endpoint. Throws if endpoint is collinear with current direction.

```ts
tangentArcTo(x: number, y: number): this
```

**Curves**

#### `bezierTo()` — Cubic bezier from current position to (x, y) via two control points.

```ts
bezierTo(cp1x: number, cp1y: number, cp2x: number, cp2y: number, x: number, y: number): this
```

**Closing & Output**

#### `close()` — Close the path and return a filled [`Sketch`](/docs/sketch#sketch).

The winding of the polygon is automatically corrected to CCW (the expected orientation for ForgeCAD sketches). If the path contains multiple sub-paths (started with subsequent `moveTo` calls), the first sub-path is the outer contour and subsequent sub-paths become holes subtracted from it.

Edge labels (assigned with `.label('name')`) are transferred to the resulting sketch and propagate through `extrude()`, `revolve()`, `loft()`, and `sweep()` into named faces on the resulting [`Shape`](/docs/core#shape).

```ts
const triangle = path().moveTo(0, 0).lineH(50).lineV(30).close();

// With a hole (second sub-path)
const frame = path()
  .moveTo(0, 0).lineH(40).lineV(30).lineH(-40).close(); // outer
  // (hole would be added with another moveTo and line sequence before close)
```

```ts
close(): Sketch
```

#### `closeLabel()` — Label the closing segment and close the path. Shorthand for labeling the implicit line from the last point back to the start, then closing.

```ts
closeLabel(name: string): Sketch
```

#### [`stroke()`](/docs/sketch#stroke) — Thicken an open polyline (centerline) into a solid filled profile with uniform width.

Expands the path into a closed profile `width` units wide (half-width on each side of the centerline). Use `'Round'` for ribs, wire traces, and organic profiles — it adds semicircular endcaps and rounds joins. Use `'Square'` (default) for sharp miter joins without endcaps.

Not the same as rounding corners of a closed polygon — for mixed sharp-and-rounded outlines, build the polygon first and apply [`filletCorners()`](/docs/sketch#filletcorners).

```ts
// Square-join L-bracket
const bracket = path().moveTo(0, 0).lineH(50).lineV(-70).lineAngled(20, 235).stroke(4);

// Round-join rib
const rib = path().moveTo(0, 0).lineH(60).stroke(6, 'Round');

// Equivalent standalone form
const wire = stroke([[0, 0], [50, 0], [50, -70]], 4);
```

and semicircular endcaps.

```ts
stroke(width: number, join?: "Round" | "Square"): Sketch
```

#### `label()` — Label the most recently added segment. Labels are born here and grow into face names when the sketch is extruded, lofted, swept, or revolved.

Labels must be unique within a path. Each segment can have at most one label.

```ts
label(name: string): this
```

**Other**

#### `getX()` — Current cursor X position.

```ts
getX(): number
```

#### `getY()` — Current cursor Y position.

```ts
getY(): number
```

#### `lineBy()` — Draw a line by a relative `(dx, dy)` displacement from the current cursor.

```ts
lineBy(dx: number, dy: number): this
```

#### `arcBy()` — Draw an arc to a point offset from the current cursor.

```ts
arcBy(dx: number, dy: number, radius: number, clockwise?: boolean): this
```

#### `bezierBy()` — Draw a cubic Bezier using control points relative to the current cursor.

```ts
bezierBy(dcp1x: number, dcp1y: number, dcp2x: number, dcp2y: number, dx: number, dy: number): this
```

#### `arcAround()` — Arc around a known center point, sweeping by the given angle. Radius is derived from the distance between the current position and the center. Positive sweep = CCW (math convention), negative = CW.

```js
// Arc 90° CCW around (50, 50)
path().moveTo(70, 50).arcAround(50, 50, 90)
// Arc 45° CW around the origin
path().moveTo(10, 0).arcAround(0, 0, -45)
```

```ts
arcAround(cx: number, cy: number, sweepDeg: number): this
```

#### `arcAroundRelative()` — Arc around a center point given as an offset from the current position. `(dx, dy)` is the vector from the current point to the center. Positive sweep = CCW (math convention), negative = CW.

```js
// Arc 90° CCW around a center 20 units to the right
path().moveTo(50, 50).arcAroundRelative(20, 0, 90)
// Equivalent to: path().moveTo(50, 50).arcAround(70, 50, 90)
```

```ts
arcAroundRelative(dx: number, dy: number, sweepDeg: number): this
```

#### `smoothCapTo()` — Smooth three-arc end cap from the current position to (endX, endY). Inserts: small corner arc → large cap arc → small corner arc, all G1-continuous.

```ts
smoothCapTo(endX: number, endY: number, cornerRadius: number, capRadius: number): this
```

#### `tangentBezierTo()` — G1-continuous cubic bezier — first control point is auto-derived from the current tangent direction. `weight` controls how far the auto-placed control point extends along the tangent (default: 1/3 of the chord).

The second control point `(cp2x, cp2y)` must be provided — it controls the arrival curvature. For a fully automatic smooth curve, see `smoothThrough`.

```ts
tangentBezierTo(cp2x: number, cp2y: number, x: number, y: number, weight?: number): this
```

#### `smoothThrough()` — Catmull-Rom spline through a list of waypoints from the current position. The current position is included as the first point. The last waypoint becomes the new cursor position.

```ts
smoothThrough(waypoints: [ number, number ][], tension?: number): this
```

#### `nurbsTo()` — Rational B-spline edge to (x, y) with explicit control points and weights.

The control points define the B-spline shape between the current position and (x, y). The current position is NOT included in `controlPoints` — it is automatically prepended. The endpoint (x, y) is the last control point.

```ts
nurbsTo(controlPoints: [ number, number ][], opts?: { weights?: number[]; degree?: number; }): this
```

#### `exactArcTo()` — Exact circular arc to (x, y) using a rational quadratic NURBS.

Unlike `arcTo()` which tessellates to a polyline, this preserves the exact arc definition. When extruded through the OCCT backend, it produces a true cylindrical face — not a faceted approximation.

```ts
exactArcTo(x: number, y: number, opts?: { radius?: number; clockwise?: boolean; }): this
```

#### [`fillet()`](/docs/core#fillet) — Round the last corner (the junction between the previous two segments) with a tangent arc of the given radius.

Must be called after at least two line/arc segments that form a corner. The fillet trims back both segments and inserts a tangent arc.

```js
path().moveTo(0,0).lineTo(10,0).lineTo(10,10).fillet(2).lineTo(0,10).close()
```

```ts
fillet(radius: number): this
```

#### [`chamfer()`](/docs/core#chamfer) — Chamfer the last corner with a straight cut of the given distance.

```js
path().moveTo(0,0).lineTo(10,0).lineTo(10,10).chamfer(2).lineTo(0,10).close()
```

```ts
chamfer(distance: number): this
```

#### `mirror()` — Mirror all existing segments across an axis and append the mirrored copy in reverse order, creating a symmetric path. The axis passes through the current cursor position.

'y' mirrors across the local Y-axis (flips X), or `[nx, ny]` for an arbitrary axis direction.

```js
// Build right half, mirror to get full symmetric profile
path().moveTo(0,0).lineTo(10,0).lineTo(10,5).mirror('x').close()
```

```ts
mirror(axis: "x" | "y" | [ number, number ]): this
```

#### `toPolyline()` — Return the open path as a sampled 2D polyline.

This is for construction geometry such as guide rails, measured centerlines, and curve-driven helpers where the authored path should stay open instead of becoming a filled sketch or stroked profile.

```ts
const rail = path()
  .moveTo(24, 0)
  .bezierTo(32, 44, 28, 92, 18, 120)
  .toPolyline();
```

```ts
toPolyline(): [ number, number ][]
```

#### `closeOffset()` — Close the path and return an offset version of the filled Sketch. Positive delta expands outward, negative shrinks inward.

```ts
closeOffset(delta: number, join?: "Round" | "Square" | "Miter"): Sketch
```

### `HermiteCurve3D`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `p0` | `Vec3` | Start position |
| `p1` | `Vec3` | End position |
| `t0` | `Vec3` | Scaled tangent at start (direction * weight * chordLength) |
| `t1` | `Vec3` | Scaled tangent at end (direction * weight * chordLength) |
| `chordLength` | `number` | Chord length (straight-line distance between endpoints) |

**Methods:**

#### `pointAt()` — Evaluate position at parameter t ∈ [0, 1]

```ts
pointAt(t: number): Vec3
```

#### `tangentAt()` — Evaluate tangent (first derivative) at parameter t ∈ [0, 1]

```ts
tangentAt(t: number): Vec3
```

#### `curvatureAt()` — Evaluate curvature vector (second derivative) at parameter t ∈ [0, 1]

```ts
curvatureAt(t: number): Vec3
```

#### `sample()` — Sample the curve as a polyline of evenly-spaced parameter values.

```ts
sample(count?: number): Vec3[]
```

#### `length()` — Approximate arc length by sampling.

```ts
length(samples?: number): number
```

#### `sampleAdaptive()` — Sample with adaptive density — more points where curvature is higher. Returns at least `minCount` points, up to `maxCount`.

```ts
sampleAdaptive(minCount?: number, maxCount?: number): Vec3[]
```

#### `toPolyline()` — Convert to a format compatible with sweep() path input.

```ts
toPolyline(samples?: number): Vec3[]
```

### `QuinticHermiteCurve3D`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `p0` | `Vec3` | Start position |
| `p1` | `Vec3` | End position |
| `t0` | `Vec3` | Scaled tangent at start (direction * weight * chordLength) |
| `t1` | `Vec3` | Scaled tangent at end (direction * weight * chordLength) |
| `c0` | `Vec3` | Scaled second derivative at start (curvature * weight² * chordLength²) |
| `c1` | `Vec3` | Scaled second derivative at end (curvature * weight² * chordLength²) |
| `chordLength` | `number` | Chord length (straight-line distance between endpoints) |

**Methods:**

#### `pointAt()` — Evaluate position at parameter t ∈ [0, 1]

```ts
pointAt(t: number): Vec3
```

#### `tangentAt()` — Evaluate tangent (first derivative, normalized) at parameter t ∈ [0, 1]

```ts
tangentAt(t: number): Vec3
```

#### `curvatureAt()` — Evaluate curvature vector (second derivative) at parameter t ∈ [0, 1]

```ts
curvatureAt(t: number): Vec3
```

#### `sample()` — Sample the curve as a polyline of evenly-spaced parameter values.

```ts
sample(count?: number): Vec3[]
```

#### `length()` — Approximate arc length by sampling.

```ts
length(samples?: number): number
```

#### `sampleAdaptive()` — Sample with adaptive density — more points where curvature is higher. Returns at least `minCount` points, up to `maxCount`.

```ts
sampleAdaptive(minCount?: number, maxCount?: number): Vec3[]
```

#### `toPolyline()` — Convert to a format compatible with sweep() path input.

```ts
toPolyline(samples?: number): Vec3[]
```

### `ProductSkin`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `name` | `string` | — |
| `shape` | `Shape` | — |
| `axis` | `ProductSkinAxis` | — |
| `stations` | `ProductStationSpec[]` | — |
| `rails` | `Record<string, ProductRailSpec>` | — |

**Methods:**

#### [`toShape()`](/docs/sdf#toshape) — Return the renderable shape generated for this product skin.

```ts
toShape(): Shape
```

#### `with()` — Create a group containing this skin plus named child details.

```ts
with(...children: GroupInput[]): ShapeGroup
```

#### `integrate()` — Boolean-union structural details into the skin body.

```ts
integrate(...details: Shape[]): Shape
```

#### `uv()` — Create a side/u/v surface-ref query on this skin.

```ts
uv(side: ProductSkinSide, u?: number, v?: number): ProductSkinRefQuery
```

**`ProductSkinSide`** — Semantic side of a ProductSkin. `back` is accepted as an alias for `rear`.

`"left" | "right" | "top" | "bottom" | "front" | "rear" | "back"`

**`ProductSkinRefQuery`**

| Option | Type | Description |
|--------|------|-------------|
| `side` | `ProductSkinSide` | Side of the product skin. `front` is the minimum axis cap, `rear`/`back` is the maximum axis cap. |
| `u?` | `number` | Across-side parameter for side refs. Defaults to 0.5. |
| `v?` | `number` | Along-axis parameter, 0 at the first cap and 1 at the rear/back cap. Defaults to 0.5. |
| `offset?` | `number` | Positive distance away from the surface along the resolved normal. |

#### `ref()` — Resolve a named ref published with Product.skin().refs(...).

```ts
ref(name: string): ProductSurfaceRef
```

#### `curveOnSurface()` — Create a sampled curve as a sequence of surface refs on this skin.

```ts
curveOnSurface(name: string, points: Array<Partial<ProductSkinRefQuery> & { side: ProductSkinSide; }>): ProductSurfaceRef[]
```

#### `surface()` — Create a fluent surface helper for refs and conformal features on one side of this skin.

Use this when several refs or ribbons share the same skin side; side-local helpers keep path points concise and make it harder to mix sides accidentally.

```ts
surface(side: ProductSkinSide): ProductSurfaceBuilder
```

#### `stationAt()` — Interpolate center, width, and depth at a normalized v or absolute axis value.

```ts
stationAt(vOrAxis: number): { ... }
```

**`ProductProfileKind`**

`"oval" | "roundedRect" | "circle" | "superEllipse" | "custom"`

#### `frame()` — Build a local surface frame from a side/u/v query.

```ts
frame(query: ProductSkinRefQuery): ProductSurfaceFrame
```

`ProductSurfaceFrame`: `{ point: Vec3, normal: Vec3, tangentU: Vec3, tangentV: Vec3, matrix: Mat4, skin: string }`

### `ProductSurfaceRef`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `name` | `string | undefined` | — |

**Methods:**

#### `frame()` — Resolve this semantic surface ref into a point, normal, tangents, and placement matrix.

```ts
frame(overrides?: Partial<ProductSkinRefQuery>): ProductSurfaceFrame
```

#### `with()` — Return a copy of this ref with side/u/v/offset overrides.

```ts
with(overrides: Partial<ProductSkinRefQuery>): ProductSurfaceRef
```

#### `attach()` — Place a detail shape or group on this ref's local surface frame.

```ts
attach(detail: Shape | ShapeGroup, options?: ProductAttachOptions): Shape | ShapeGroup
```

`ProductAttachOptions`: `{ offset?: number, inset?: number }`

#### `querySpec()` — Return the serializable side/u/v query behind this ref.

```ts
querySpec(): ProductSkinRefQuery
```

### `ProductSurfaceBuilder`

Fluent helper bound to one ProductSkin side for refs and side-local conformal features.

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `side` | `ProductSkinSide` | — |

**Methods:**

#### `ref()` — Create a ref on this skin side.

```ts
ref(u?: number, v?: number, offset?: number): ProductSurfaceRef
```

#### `uv()` — Create a side/u/v query on this skin side.

```ts
uv(u?: number, v?: number, offset?: number): ProductSkinRefQuery
```

#### `frame()` — Resolve a point/frame on this surface using the builder's side.

```ts
frame(query?: Partial<ProductSkinRefQuery>): ProductSurfaceFrame
```

#### `ribbon()` — Start a conformal ribbon on this skin side.

Path points use side-local `u`/`v` coordinates; this builder supplies the side. The returned ProductRibbonBuilder is already bound to the source skin and can be further configured before build(). Use `widthSamples` >= 3 when the ribbon must visibly wrap over curved product sections instead of behaving like a flat strip.

```ts
ribbon(name: string, points: ProductSurfacePathPoint[], options?: ProductRibbonBuildOptions): ProductRibbonBuilder
```

**`ProductSurfacePathPoint`** — Side-local path point for Product.surface(side).ribbon(...); the surface helper supplies `side`.
- `u?: number` — Across-side parameter on the bound side. Defaults to 0.5.
- `v?: number` — Along-axis parameter, 0 at the first cap and 1 at the rear/back cap. Defaults to 0.5.
- `offset?: number` — Positive distance away from the surface along the resolved normal.

**`ProductRibbonBuildOptions`** — Options shared by Product.ribbon() builders and Product.surface(...).ribbon(...).

| Option | Type | Description |
|--------|------|-------------|
| `width?` | `number` | Width across the surface in millimeters. |
| `thickness?` | `number` | Solid thickness outward from the source surface in millimeters. |
| `offset?` | `number` | Positive clearance between the source surface and the ribbon's inner face. |
| `samples?` | `number` | Samples along the ribbon path. Higher values bend more smoothly. |
| `widthSamples?` | `number` | Samples across the ribbon width. Use 3+ to visibly wrap over curved cross-sections. |
| `resolution?` | `number` | Tessellation resolution passed to the lowered NURBS surface. |
| `material?` | `ProductMaterial` | Apply a product material preset to the ribbon. |
| `color?` | `string` | Apply a simple color override. |

`ProductMaterial`: `{ color?: string, material?: ShapeMaterialProps }`

**`ShapeMaterialProps`**

| Option | Type | Description |
|--------|------|-------------|
| `metalness?` | `number` | Metalness factor (0 = dielectric, 1 = metal). Default: 0.05 |
| `roughness?` | `number` | Roughness factor (0 = mirror, 1 = fully diffuse). Default: 0.35 |
| `emissive?` | `string` | Emissive glow color (hex string, e.g. "#ff6b35"). |
| `emissiveIntensity?` | `number` | Emissive intensity multiplier. Default: 1 |
| `opacity?` | `number` | Opacity (0 = fully transparent, 1 = fully opaque). Default: 1 |
| `wireframe?` | `boolean` | Render as wireframe. Default: false |
| `clearcoat?` | `number` | Clearcoat intensity (0–1). Default: 0.1 |
| `clearcoatRoughness?` | `number` | Clearcoat roughness (0–1). Default: 0.4 |
| `transmission?` | `number` | Glass/translucency transmission factor (0–1). Renderer support depends on target. |
| `ior?` | `number` | Index of refraction for transmissive materials. Typical glass is ~1.45. |
| `thickness?` | `number` | Approximate transmissive volume thickness in model units. |
| `specularIntensity?` | `number` | Specular highlight intensity (0–1). |
| `specularColor?` | `string` | Specular highlight tint. |
| `reflectivity?` | `number` | Reflection strength for supported renderers (0–1). |

### `ProductSkinBuilder`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `name` | `string` | — |

**Methods:**

#### `axis()` — Choose the primary station axis for the skin loft.

```ts
axis(axis: ProductSkinAxis): this
```

**`ProductSkinAxis`** — Primary world axis used to order ProductSkin loft stations.

`"X" | "Y" | "Z"`

#### `stations()` — Set named cross-section stations for the product skin.

```ts
stations(stations: Array<ProductStationBuilder | ProductStationSpec>): this
```

`ProductStationSpec`: `{ name: string, center: Vec3, profile: ProductStationProfile, crown?: number }`

`ProductStationProfile`: `{ sketch: Sketch, width: number, depth: number, kind: ProductProfileKind, radius?: number, exponent?: number }`

#### `rails()` — Attach named guide rails for product-skin construction and downstream surface references.

```ts
rails(rails: Record<string, ProductRailSpec>): this
```

`ProductRailSpec`: `{ kind: ProductRailKind, points: Vec3[], degree?: number, name?: string }`

**`ProductRailKind`**

`"bezier" | "nurbs" | "polyline"`

#### `ref()` — Publish a named semantic surface ref on the skin.

```ts
ref(name: string, query: ProductSkinRefQuery): this
```

#### `refs()` — Publish multiple named semantic surface refs on the skin.

```ts
refs(refs: Record<string, ProductSkinRefQuery>): this
```

#### `uv()` — Create a side/u/v surface-ref query for use in refs(...) or Product.ref(...).

```ts
uv(side: ProductSkinSide, u?: number, v?: number): ProductSkinRefQuery
```

#### `material()` — Apply a product material preset to the lowered skin.

```ts
material(material: ProductMaterial): this
```

#### `color()` — Apply a simple color override to the lowered skin.

```ts
color(color: string): this
```

#### `edgeLength()` — Set the sampled loft target edge length.

```ts
edgeLength(value: number): this
```

#### `wall()` — Record intended wall thickness for product design metadata. Use explicit shelling when the model needs real inner-wall geometry.

```ts
wall(thickness: number): this
```

#### `build()` — Lower stations and refs into a ProductSkin body.

```ts
build(): ProductSkin
```

### `ProductStationBuilder`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `name` | `string` | — |

**Methods:**

#### `at()` — Position this station in world coordinates.

```ts
at(point: Vec3): this
```

#### `z()` — Convenience for traditional Z-up section stacks.

```ts
z(z: number): this
```

#### `y()` — Convenience for product bodies running front-to-back along Y.

```ts
y(y: number): this
```

#### `x()` — Convenience for product bodies running left-to-right along X.

```ts
x(x: number): this
```

#### `oval()` — Use an oval cross-section with full width and depth dimensions.

```ts
oval(width: number, depth: number, options?: { segments?: number; }): this
```

#### `superEllipse()` — Use a superellipse cross-section for soft-square product surfaces.

```ts
superEllipse(width: number, depth: number, options?: ProductStationSuperEllipseOptions): this
```

`ProductStationSuperEllipseOptions`: `{ segments?: number, exponent?: number }`

#### [`roundedRect()`](/docs/sketch#roundedrect) — Use a rounded-rectangle cross-section with the given corner radius.

```ts
roundedRect(width: number, depth: number, radius: number): this
```

#### [`circle()`](/docs/sketch#circle) — Use a circular cross-section from a full diameter.

```ts
circle(diameter: number, options?: { segments?: number; }): this
```

#### `custom()` — Use a custom 2D sketch as the station cross-section.

```ts
custom(sketch: Sketch, width: number, depth: number): this
```

#### `crown()` — Set the station crown amount for soft product-section intent.

```ts
crown(amount: number): this
```

#### `toSpec()` — Return the immutable station spec consumed by Product.skin().

```ts
toSpec(): ProductStationSpec
```

### `ProductPanelBuilder`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `name` | `string` | — |

**Methods:**

#### `rounded()` — Use a rounded rectangle panel profile.

```ts
rounded(width: number, height: number, radius?: number): this
```

#### `oval()` — Use an oval panel profile.

```ts
oval(width: number, height: number): this
```

#### `profile()` — Use a custom 2D panel profile.

```ts
profile(profile: Sketch): this
```

#### `thickness()` — Set panel extrusion thickness.

```ts
thickness(thickness: number): this
```

#### `material()` — Apply a product material preset to the panel.

```ts
material(material: ProductMaterial): this
```

#### `color()` — Apply a simple color override to the panel.

```ts
color(color: string): this
```

#### `build()` — Build the panel in local coordinates.

```ts
build(): Shape
```

#### `attachTo()` — Build and attach this panel to a ProductSurfaceRef.

```ts
attachTo(ref: ProductRefInput, options?: ProductPanelAttachOptions): Shape
```

**`ProductRefInput`**

`ProductSurfaceRef`


`ProductPanelAttachOptions`: `{ at?: Partial<ProductSkinRefQuery>, thickness?: number, material?: ProductMaterial, color?: string }`

### `ProductRibbonBuilder`

Builder for thin trim, label, grip, and split-line features that bend with a ProductSkin surface.

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `name` | `string` | — |

**Methods:**

#### `on()` — Follow a ProductSkin with side/u/v path queries or refs.

This is the highest-fidelity mode because every interpolated sample is resolved through ProductSkin.frame(), so the ribbon bends along the selected side as station width/depth changes. All query path points must stay on one side; split side transitions into separate ribbons.

```ts
on(skin: ProductSkin, points: ProductRibbonPathPoint[], options?: ProductRibbonBuildOptions): this
```

**`ProductRibbonPathPoint`** — Path point for Product.ribbon().on(...): either a side/u/v query or a resolved surface ref.

`ProductSkinRefQuery | ProductSurfaceRef`

#### `fromRefs()` — Follow explicit surface refs.

Useful for named refs or paths assembled elsewhere. The builder resolves each ref frame and interpolates between those frames; use on(skin, points) when you need full skin-side sampling between sparse control points.

```ts
fromRefs(points: ProductSurfaceRef[], options?: ProductRibbonBuildOptions): this
```

#### `width()` — Set ribbon width in millimeters.

```ts
width(width: number): this
```

#### `thickness()` — Set solid thickness outward from the source surface in millimeters.

```ts
thickness(thickness: number): this
```

#### `offset()` — Set positive clearance between the source surface and the ribbon's inner face.

```ts
offset(offset: number): this
```

#### `samples()` — Set samples along the path.

```ts
samples(samples: number): this
```

#### `widthSamples()` — Set samples across the width. Use 3+ to bend over curved cross-sections.

```ts
widthSamples(samples: number): this
```

#### `resolution()` — Set NURBS tessellation resolution.

```ts
resolution(resolution: number): this
```

#### `material()` — Apply a product material preset.

```ts
material(material: ProductMaterial): this
```

#### `color()` — Apply a simple color override.

```ts
color(color: string): this
```

#### `build()` — Build a conformal ribbon as a thin NURBS surface solid.

```ts
build(options?: ProductRibbonBuildOptions): Shape
```

### `ProductSpoutBuilder`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `name` | `string` | — |

**Methods:**

#### `from()` — Set the skin ref this spout projects from.

```ts
from(ref: ProductSurfaceRef): this
```

#### `sections()` — Set local spout section profiles from root to mouth.

```ts
sections(sections: Array<Sketch | ProductStationBuilder | ProductStationSpec>): this
```

#### `projection()` — Set the projection length along the source ref normal.

```ts
projection(length: number): this
```

#### `edgeLength()` — Set the sampled loft target edge length for the spout.

```ts
edgeLength(value: number): this
```

#### `material()` — Apply a product material preset to the spout.

```ts
material(material: ProductMaterial): this
```

#### `color()` — Apply a simple color override to the spout.

```ts
color(color: string): this
```

#### `build()` — Build the spout in local coordinates.

```ts
build(): Shape
```

#### `attach()` — Build and place the spout on its source ref.

```ts
attach(options?: ProductAttachOptions): Shape
```

### `ProductHandleBuilder`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `name` | `string` | — |

**Methods:**

#### `between()` — Set the upper body ref and lower world anchor for the handle.

```ts
between(upper: ProductSurfaceRef, lower: Vec3): this
```

#### `spine()` — Set an explicit handle centerline from points or a rail spec.

```ts
spine(points: Vec3[] | ProductRailSpec): this
```

#### `grip()` — Set the grip cross-section profile.

```ts
grip(profile: Sketch): this
```

#### `material()` — Apply a product material preset to the grip.

```ts
material(material: ProductMaterial): this
```

#### `padMaterial()` — Apply a product material preset to handle landing pads.

```ts
padMaterial(material: ProductMaterial): this
```

#### `edgeLength()` — Set the sampled loft target edge length for the grip.

```ts
edgeLength(value: number): this
```

#### `build()` — Build the handle grip and landing pads.

```ts
build(): ProductHandleFeature
```

### `ProductHandleFeature`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `grip` | `Shape` | — |
| `upperPad` | `Shape` | — |
| `lowerPad` | `Shape` | — |

**Methods:**

#### `structural()` — Return the physical shapes that make up this handle feature.

```ts
structural(): Shape[]
```

#### [`toShape()`](/docs/sdf#toshape) — Boolean-union the handle feature into a single shape.

```ts
toShape(): Shape
```

#### `toGroup()` — Return the handle as a named ShapeGroup preserving child colors.

```ts
toGroup(): ShapeGroup
```

### `CylinderCarrier`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `name` | `string` | — |
| `kind` | `"cylinder"` | — |

**Methods:**

#### `diameter()`

```ts
diameter(value: number): this
```

#### `radius()`

```ts
radius(value: number): this
```

#### `height()`

```ts
height(value: number): this
```

#### `clearance()`

```ts
clearance(value: number): this
```

#### `center()`

```ts
center(point: Vec3): this
```

#### [`path()`](/docs/sketch#path)

```ts
path(): SurfacePathBuilder<CylinderSurfaceCoordinate>
```

#### `anchor()`

```ts
anchor(angle: number, z?: number, options?: { offset?: number; }): SurfaceAnchor<CylinderSurfaceCoordinate>
```

#### `front()`

```ts
front(options?: { z?: number; offset?: number; }): SurfaceAnchor<CylinderSurfaceCoordinate>
```

#### `back()`

```ts
back(options?: { z?: number; offset?: number; }): SurfaceAnchor<CylinderSurfaceCoordinate>
```

#### `left()`

```ts
left(options?: { z?: number; offset?: number; }): SurfaceAnchor<CylinderSurfaceCoordinate>
```

#### `right()`

```ts
right(options?: { z?: number; offset?: number; }): SurfaceAnchor<CylinderSurfaceCoordinate>
```

#### `top()`

```ts
top(options?: { angle?: number; offset?: number; }): SurfaceAnchor<CylinderSurfaceCoordinate>
```

#### `bottom()`

```ts
bottom(options?: { angle?: number; offset?: number; }): SurfaceAnchor<CylinderSurfaceCoordinate>
```

#### `pointAt()`

```ts
pointAt(coordinate: CylinderSurfaceCoordinate): Vec3
```

#### `mirrorPoint()`

```ts
mirrorPoint(point: Vec3): Vec3
```

#### `normalAt()`

```ts
normalAt(coordinate: CylinderSurfaceCoordinate): Vec3
```

#### `tangentAt()`

```ts
tangentAt(coordinate: CylinderSurfaceCoordinate, tangentHint?: Vec3): Vec3
```

#### `frameAt()`

```ts
frameAt(coordinate: CylinderSurfaceCoordinate, tangentHint?: Vec3): SurfaceFrame
```

#### `bounds()`

```ts
bounds(): SurfaceBounds
```

#### `offset()`

```ts
offset(distance: number): CylinderCarrier
```

#### `mirrorCoordinate()`

```ts
mirrorCoordinate(coordinate: CylinderSurfaceCoordinate): CylinderSurfaceCoordinate
```

#### `radiusValueWithClearance()`

```ts
radiusValueWithClearance(): number
```

### `PlaneCarrier`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `name` | `string` | — |
| `kind` | `"plane"` | — |

**Methods:**

#### `size()`

```ts
size(width: number, height: number): this
```

#### `origin()`

```ts
origin(point: Vec3): this
```

#### `normal()`

```ts
normal(normal: Vec3): this
```

#### [`path()`](/docs/sketch#path)

```ts
path(): SurfacePathBuilder<PlaneSurfaceCoordinate>
```

#### `anchor()`

```ts
anchor(x?: number, y?: number, options?: { offset?: number; }): SurfaceAnchor<PlaneSurfaceCoordinate>
```

#### `left()`

```ts
left(options?: { y?: number; offset?: number; }): SurfaceAnchor<PlaneSurfaceCoordinate>
```

#### `right()`

```ts
right(options?: { y?: number; offset?: number; }): SurfaceAnchor<PlaneSurfaceCoordinate>
```

#### `top()`

```ts
top(options?: { x?: number; offset?: number; }): SurfaceAnchor<PlaneSurfaceCoordinate>
```

#### `bottom()`

```ts
bottom(options?: { x?: number; offset?: number; }): SurfaceAnchor<PlaneSurfaceCoordinate>
```

#### `pointAt()`

```ts
pointAt(coordinate: PlaneSurfaceCoordinate): Vec3
```

#### `mirrorPoint()`

```ts
mirrorPoint(point: Vec3): Vec3
```

#### `normalAt()`

```ts
normalAt(): Vec3
```

#### `tangentAt()`

```ts
tangentAt(coordinate: PlaneSurfaceCoordinate, tangentHint?: Vec3): Vec3
```

#### `frameAt()`

```ts
frameAt(coordinate: PlaneSurfaceCoordinate, tangentHint?: Vec3): SurfaceFrame
```

#### `bounds()`

```ts
bounds(): SurfaceBounds
```

#### `offset()`

```ts
offset(distance: number): PlaneCarrier
```

#### `mirrorCoordinate()`

```ts
mirrorCoordinate(coordinate: PlaneSurfaceCoordinate): PlaneSurfaceCoordinate
```

### `ProductSkinCarrier`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `skin` | `ProductSkin` | — |
| `name` | `string` | — |
| `kind` | `"productSkin"` | — |

**Methods:**

#### `surface()`

```ts
surface(side: ProductSkinSide): ProductSkinCarrier
```

#### [`path()`](/docs/sketch#path)

```ts
path(): SurfacePathBuilder<ProductSkinSurfaceCoordinate>
```

`ProductSkinSurfaceCoordinate`: `{ kind?: "productSkin", side?: ProductSkinSide, u?: number, v?: number, offset?: number }`

#### `sideTransition()` — Return matching side-local coordinates for an explicit split-member transition.

Each SurfacePath still stays on one ProductSkin side. Use this helper to create one member ending on `from`, another starting on `to`, then join named anchors. The helper validates normalized `v`, non-empty names, adjacency, and physical coincidence before returning anchors.

```ts
sideTransition(fromSide: ProductSkinSide, toSide: ProductSkinSide, input?: ProductSkinSideTransitionInput): ProductSkinSideTransition
```

`ProductSkinSideTransitionInput`: `{ name?: string, v?: number, offset?: number }`

`ProductSkinSideTransition`: `{ name?: string, from: ProductSkinSurfaceCoordinate, to: ProductSkinSurfaceCoordinate }`

#### `sideTransitionChain()` — Return a sequence of matching side-local coordinates for an explicit multi-side split-member route.

Each adjacent side pair becomes one named transition. Build one member per side segment, add transition anchors at each returned pair, then join the anchors. The same validation as `sideTransition()` applies to every adjacent pair.

```ts
sideTransitionChain(sides: ProductSkinSide[], input?: ProductSkinSideTransitionInput): ProductSkinSideTransition[]
```

#### `sideRoute()` — Return side-local member segments for a generated multi-side split-member route.

The route still compiles as explicit members plus named-anchor joins. This helper only generates the per-side segment endpoints and transition names.

```ts
sideRoute(input: ProductSkinSideRouteInput): ProductSkinSideRoute
```

**`ProductSkinSideRouteInput`**: `name?: string`, `sides: ProductSkinSide[]`, `from: ProductSkinSurfaceCoordinate`, `to: ProductSkinSurfaceCoordinate`, `v?: number`, `offset?: number`

`ProductSkinSideRoute`: `{ name?: string, transitions: ProductSkinSideTransition[], segments: ProductSkinSideRouteSegment[] }`

**`ProductSkinSideRouteSegment`**: `name: string`, `side: ProductSkinSide`, `from: ProductSkinSurfaceCoordinate`, `to: ProductSkinSurfaceCoordinate`, `startAnchorName?: string`, `endAnchorName?: string`

#### `pointAt()`

```ts
pointAt(coordinate: ProductSkinSurfaceCoordinate): Vec3
```

#### `mirrorPoint()`

```ts
mirrorPoint(point: Vec3): Vec3
```

#### `normalAt()`

```ts
normalAt(coordinate: ProductSkinSurfaceCoordinate): Vec3
```

#### `tangentAt()`

```ts
tangentAt(coordinate: ProductSkinSurfaceCoordinate, tangentHint?: Vec3): Vec3
```

#### `frameAt()`

```ts
frameAt(coordinate: ProductSkinSurfaceCoordinate, tangentHint?: Vec3): SurfaceFrame
```

**`SurfaceFrame`**: `point: Vec3`, `normal: Vec3`, `tangentAlong: Vec3`, `tangentAcross: Vec3`, `matrix: Mat4`, `carrier: string`, `representation: SurfaceCarrierKind | string`, `coordinate: SurfaceCoordinate`

#### `bounds()`

```ts
bounds(): SurfaceBounds
```

**`SurfaceBounds`**: `u?: [ number, number ]`, `v?: [ number, number ]`, `angle?: [ number, number ]`, `z?: [ number, number ]`, `x?: [ number, number ]`, `y?: [ number, number ]`

#### `offset()`

```ts
offset(distance: number): ProductSkinCarrier
```

#### `mirrorCoordinate()`

```ts
mirrorCoordinate(coordinate: ProductSkinSurfaceCoordinate): ProductSkinSurfaceCoordinate
```

### `SurfacePath`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `carrier` | `CarrierSurface<C>` | — |
| `points` | `C[]` | — |
| `closedValue` | `boolean` | — |

**Methods:**

#### `closed()`

```ts
closed(): SurfacePath<C>
```

#### `mirror()`

```ts
mirror(): SurfacePath<C>
```

#### `coordinateAt()`

```ts
coordinateAt(t: number): C
```

#### `sample()`

```ts
sample(count?: number): SurfacePathSample<C>[]
```

#### `length()`

```ts
length(samples?: number): number
```

### `SurfacePathBuilder`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `carrier` | `CarrierSurface<C>` | — |

**Methods:**

#### `from()`

```ts
from(coordinate: C): this
```

#### `through()`

```ts
through(coordinate: C): this
```

#### `to()`

```ts
to(coordinate: C): this
```

#### `around()`

```ts
around(input: { z: number; fromAngle: number; toAngle: number; offset?: number; }): this
```

#### `closed()`

```ts
closed(): this
```

#### `mirror()`

```ts
mirror(): SurfacePath<C>
```

#### `build()`

```ts
build(): SurfacePath<C>
```

#### `sample()`

```ts
sample(count?: number): SurfacePathSample<C>[]
```

### `SurfaceBand`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `centerPath` | `SurfacePath<C>` | — |
| `widthProfile` | `WidthProfile` | — |
| `capStyle` | `SurfaceBandCap` | — |

**Methods:**

#### `widthAt()`

```ts
widthAt(t: number): number
```

#### `boundaries()`

```ts
boundaries(samples?: number): SurfaceBandBoundarySample[]
```

#### `withHole()` — Return a new band with a named member-local rounded-slot hole region recorded as inspectable intent.

```ts
withHole(name: string, input: SurfaceBandHoleInput): SurfaceBand<C>
```

#### `holes()` — Resolve recorded hole regions into member-local across/along loops.

```ts
holes(): SurfaceBandHoleRegion[]
```

### `SurfaceBodyBuilder`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `name` | `string` | — |

**Methods:**

#### `carrier()`

```ts
carrier(carrier: CarrierSurface): this
```

#### `member()`

```ts
member(name: string): SurfaceMemberBuilder
```

#### `join()`

```ts
join(from: string, to: string | string[]): SurfaceJoinBuilder
```

#### `autoJoinAtSharedAnchors()`

```ts
autoJoinAtSharedAnchors(): this
```

#### `build()`

```ts
build(): Shape | ShapeGroup
```

### `SurfaceMemberBuilder`

#### `plate()`

```ts
plate(): this
```

#### `band()`

```ts
band(): this
```

#### `at()`

```ts
at(anchor: SurfaceAnchor<C>): this
```

#### `size()`

```ts
size(width: number, height: number): this
```

#### [`path()`](/docs/sketch#path)

```ts
path(path: SurfacePath<C> | SurfacePathBuilder<C>): this
```

#### `section()`

```ts
section(section: MemberSectionInput): this
```

#### `cap()`

```ts
cap(style: SurfaceBandCap): this
```

#### [`slot()`](/docs/sketch#slot)

```ts
slot(name: string, feature: MemberFeature | RoundedSlotBuilder): this
```

#### `cutout()`

```ts
cutout(name: string, feature: MemberFeature | RoundedSlotBuilder): this
```

#### `counterbore()`

```ts
counterbore(name: string, feature: MemberFeature | CounterboreBuilder): this
```

#### `anchorAt()` — Add a named anchor at a carrier surface coordinate for explicit member joins.

```ts
anchorAt(name: string, coordinate: C | SurfaceAnchor<C>): this
```

#### `features()`

```ts
features(features: MemberFeature | MemberFeature[]): this
```

#### `profile()`

```ts
profile(name: string, options?: { depth?: number; height?: number; }): this
```

#### `mirrorOf()`

```ts
mirrorOf(memberName: string): SurfaceBodyBuilder
```

#### `member()`

```ts
member(name: string): SurfaceMemberBuilder
```

#### `join()`

```ts
join(from: string, to: string | string[]): SurfaceJoinBuilder
```

#### `autoJoinAtSharedAnchors()`

```ts
autoJoinAtSharedAnchors(): SurfaceBodyBuilder
```

#### `build()`

```ts
build(): Shape | ShapeGroup
```

### `SurfaceJoinBuilder`

#### `betweenAnchors()` — Select named anchors on the source and target members before lowering this join.

```ts
betweenAnchors(fromAnchor: string, toAnchor: string): this
```

#### `blend()`

```ts
blend(input?: { radius?: number; style?: string; priority?: number; continuity?: string; }): SurfaceBodyBuilder
```

### `CounterboreBuilder`

#### `at()`

```ts
at(input: { along?: number; across?: number; z?: number; }): this
```

#### `named()`

```ts
named(name: string): MemberFeature
```

#### `toFeature()`

```ts
toFeature(name?: string): MemberFeature
```

### `RoundedSlotBuilder`

#### `verticalTravel()`

```ts
verticalTravel(value: number): this
```

#### `at()`

```ts
at(input: { along?: number; across?: number; z?: number; }): this
```

#### `named()`

```ts
named(name: string): MemberFeature
```

#### `toFeature()`

```ts
toFeature(name?: string): MemberFeature
```

---

## Constants

### `Surface`

- `Plane(options: SurfacePlaneOptions): Shape` — Create a finite analytic plane sheet that can be trimmed, sewn, thickened, or used as a low-level face.
- `Cylinder(options: SurfaceCylinderOptions): Shape` — Create a finite analytic cylindrical sheet, optionally bounded by start/end angles.
- `Cone(options: SurfaceConeOptions): Shape` — Create a finite analytic conical or frustum sheet, optionally bounded by start/end angles.
- `Sphere(options: SurfaceSphereOptions): Shape` — Create a finite analytic spherical sheet bounded by longitude and latitude ranges.
- `Torus(options: SurfaceTorusOptions): Shape` — Create a finite analytic torus sheet bounded by major and tube angle ranges.
- `Nurbs(controlGrid: Vec3[][], options?: NurbsSurfaceOptions): Shape`
- `Ruled(curveA: ExactCurveInput, curveB: ExactCurveInput, options?: SurfaceCommonOptions): Shape`
- `Patch(curves: { bottom: ExactCurveInput; top: ExactCurveInput; left: ExactCurveInput; right: ExactCurveInput; }, options?: SurfacePatchOptions): Shape`
- `Boundary(input: SurfaceBoundaryInput): Shape`
- `Fill(input: SurfaceFillInput): Shape`
- `Sew(shapes: Shape[], options?: { tolerance?: number; }): Shape`
- `Solid(input: Shape | Shape[], options?: SurfaceSolidOptions): Shape` — Sew surface faces or consume an existing sewn shell and make a solid B-rep.
- `Extend(shape: Shape, options: SurfaceExtendOptions): Shape`
- `Trim(shape: Shape, tool: Shape | SurfacePlaneOp): Shape`
- `Split(shape: Shape, tool: Shape | SurfacePlaneOp): [ Shape, Shape ]`
- `Match(shape: Shape, options: { edge: "u0" | "u1" | "v0" | "v1"; target: EdgeRef; continuity?: SurfaceContinuity; }): Shape`
- `MatchEdge(shape: Shape, options: { edge: "u0" | "u1" | "v0" | "v1"; target: EdgeRef; continuity?: SurfaceContinuity; }): Shape`

### `Blend`

- `Edge(options: BlendEdgeOptions): Shape`
- `Surface(options: BlendSurfaceOptions): Shape`

### `Analysis`

- `EdgeContinuity(shape: Shape, options?: EdgeContinuityThresholds): EdgeContinuityReport`
- `SurfaceContinuity(shape: Shape, options?: EdgeContinuityThresholds): EdgeContinuityReport`
- `CurvatureComb(input: NurbsCurve3D | EdgeRef, options?: { samples?: number; }): CurvatureSample[]`
- `SurfaceHealth(shape: Shape, options?: { tinyEdgeThreshold?: number; sliverThreshold?: number; }): SurfaceHealthReport`
- `BRepValidity(shape: Shape, options?: BRepValidityOptions): BRepValidityReport` — Validate B-rep/shell/solid structure and return closedness, manifoldness, orientation, and issue diagnostics.

### `Product`

- `skin(name: string): ProductSkinBuilder` — Start a named product skin builder.
- `station(name: string): ProductStationBuilder` — Start a named cross-section station for Product.skin(...).stations(...).
- `rail: { bezier(points: Vec3[], options?: { name?: string; }): ProductRailSpec; nurbs(points: Vec3[], options?: { degree?: number; name?: string; }): ProductRailSpec; polyline(points: Vec3[], options?: { name?: string; }): ProductRailSpec; }` — Namespaced rail builders for product skin guide rails and handle spines.
- `profiles: { ... }` — Namespaced product profile helpers for stations, panels, trims, and openings.
- `materials: { ... }` — Namespaced product material presets for molded plastic, rubber, metal, and transparent parts.
- `applyMaterial(shape: Shape, preset: ProductMaterial | undefined): Shape` — Apply a product material preset to a Shape.
- `scenePreset(name: ProductScenePreset): void` — Apply an opinionated scene preset for product review renders.
- `ovalProfile(width: number, depth: number, options?: ProductProfileOptions): Sketch` — Create a centered oval profile from full width/depth dimensions.
- `roundedRectProfile(width: number, depth: number, radius: number): Sketch` — Create a centered rounded-rectangle profile.
- `circleProfile(diameter: number, options?: ProductProfileOptions): Sketch` — Create a centered circular profile from full diameter.
- `superEllipseProfile(width: number, depth: number, options?: ProductSuperEllipseOptions): Sketch` — Create a centered superellipse profile for soft-square product sections.
- `profileSize(sketch: Sketch): { width: number; depth: number; }` — Measure the width and depth of a 2D profile sketch.
- `describeProfile(sketch: Sketch, kind?: ProductProfileKind, radius?: number): ProductProfileDescriptor` — Describe a custom sketch as a product profile.
- `scaleProfileTo(sketch: Sketch, width: number, depth: number): Sketch` — Scale an existing profile sketch to a target width/depth.
- `ref(skin: ProductSkin, query: ProductSkinRefQuery): ProductSurfaceRef` — Create an ad-hoc ProductSurfaceRef from a skin and side/u/v query.
- `surface(skin: ProductSkin, side: ProductSkinSide): ProductSurfaceBuilder` — Create a fluent surface helper for refs and conformal features on one side of a skin. Equivalent to skin.surface(side), useful when writing in Product.* namespace style.
- `panel(name: string): ProductPanelBuilder` — Start a panel feature builder.
- `ribbon(name: string): ProductRibbonBuilder` — Start a conformal ribbon/trim builder for details that should bend with a ProductSkin. Call .on(skin, points) for side/u/v sampling or .fromRefs(points) for explicit surface refs, then configure width, thickness, offset, sampling, material, and color before build().
- `spout(name: string): ProductSpoutBuilder` — Start a spout/nozzle feature builder.
- `handle(name: string): ProductHandleBuilder` — Start a handle feature builder.
- `place(detail: Shape | ShapeGroup, ref: ProductRefInput, options?: ProductAttachOptions): Shape | ShapeGroup` — Place a shape or group on a ProductSurfaceRef.
- `landing(name: string, radius?: number, material?: ProductMaterial): Shape` — Small blended landing volume for manual structural bridges and connection proofs.

### `Carrier`

- `cylinder(name: string): CylinderCarrier` — Create an analytic cylinder carrier for bottles, limbs, tubes, guards, and cuffs.
- `plane(name: string): PlaneCarrier` — Create an analytic plane carrier for plates and local flat construction surfaces.
- `productSkin(skin: ProductSkin): ProductSkinCarrier` — Adapt an existing ProductSkin into the general surface-member carrier protocol.

### `SurfaceMembers`

- `Body(name: string): SurfaceBodyBuilder` — Start a surface-member body builder for straps, inlays, guards, braces, cuffs, and similar physical members that live on a carrier surface.
- `Band: typeof SurfaceBand`
- `band<C extends SurfaceCoordinate>(path: SurfacePath<C> | SurfacePathBuilder<C>, width: WidthProfile, cap?: SurfaceBandCap): SurfaceBand<C>`

### `Slot`

- `rounded(input: { length: number; width: number; }): RoundedSlotBuilder` — Create a rounded member-local slot feature.

### `Counterbore`

- `cylindrical(input: { diameter: number; clearanceDiameter: number; depth: number; }): CounterboreBuilder` — Create a cylindrical member-local counterbore feature.

### `Ribs`

- `repeated(input: { count: number; height: number; }): MemberFeature` — Create repeated ribs that belong to a surface member before lowering.

---

<!-- generated/assembly.md -->

# Assembly API

Kinematic assemblies, joints, couplings, and robot export.

## Contents

- [Assembly & Joints](#assembly-joints) — `bomToCsv`, `assembly`, `joint`
- [Assembly](#assembly) — Structure, Connectors, References, Joints, Solving
- [ImportedAssembly](#importedassembly)
- [SolvedAssembly](#solvedassembly)
- [MateBuilder](#matebuilder)

## Functions

### Assembly & Joints

#### `bomToCsv()` — Convert an array of BOM rows into a CSV string.

Produces a CSV with columns: `part`, `qty`, `material`, `process`, `tolerance`, `notes`. String values are quoted and internal double-quotes are escaped. Prefer calling `solvedAssembly.bomCsv()` directly — this function is exposed for custom BOM processing.

```ts
bomToCsv(rows: BomRow[]): string
```

**`BomRow`**: `part: string`, `qty: number`, `material?: string`, `process?: string`, `tolerance?: string`, `notes?: string`, `metadata?: PartMetadata`

**`PartMetadata`**

| Option | Type | Description |
|--------|------|-------------|
| `tags?` | `string \| readonly string[]` | Viewport organization tags applied to scene objects produced from this part. |
| `material?`, `process?`, `tolerance?`, `qty?`, `notes?`, `densityKgM3?`, `massKg?` | | — |

#### `assembly()` — Create an assembly container with named parts and joints for kinematic mechanisms.

**Use this from iteration 1 for any model with moving parts.** Hinges, sliders, gears, articulated fingers, doors — all start with `assembly()`, not with manual rotation math. Don't build a static "extended pose" first and refactor to an assembly later: joint sliders, animations, sweeps, collision detection, and robot export all flow from the kinematic graph.

An assembly models a mechanism as a directed graph of parts connected by joints. Parts are the nodes; joints are directed edges from parent to child. The graph must be a forest (no cycles). Root parts (those with no incoming joint) are anchored to world space.

Three joint types are supported: `'revolute'` (hinge), `'prismatic'` (slider), and `'fixed'` (rigid attachment). Use `addPart()` to add geometry, `addJoint()` (or the shorthands `addRevolute()`, `addPrismatic()`, `addFixed()`) to connect parts, and `solve()` to compute world-space positions at a given joint state.

The higher-level `connect()` API uses declared **connectors** to compute joint frames automatically. The `match()` API uses typed connectors (with gender and type metadata) for automatic compatibility validation and joint creation.

For multi-file assemblies, a file that returns an `Assembly` is importable via [`require()`](/docs/core#require) and yields an `ImportedAssembly`. Use `mergeInto()` to flatten a sub-assembly into a parent assembly.

```ts
const mech = assembly("Arm")
  .addPart("base", box(80, 80, 20).translate(0, 0, -10), {
    metadata: { material: "PETG", process: "FDM", qty: 1 },
  })
  .addPart("link", box(140, 24, 24).translate(0, -12, -12))
  .addRevolute("shoulder", "base", "link", {
    axis: [0, 1, 0],
    min: -30, max: 120, default: 25,
    frame: Transform.identity().translate(0, 0, 20),
  });

return mech; // auto-solved at defaults, renders all parts
```

```ts
assembly(name?: string): Assembly
```

#### `joint()` — Create a revolute joint that auto-generates a parameter slider and rotates the shape.

This is a convenience wrapper for single-shape, single-joint use cases. It calls `param()` to create a named angle slider, then applies `rotateAroundAxis()` to the shape. Use the full `Assembly` API for mechanisms with multiple parts and joints.

```ts
const arm = joint("Shoulder", armShape, [0, 0, 20], {
  axis: [0, 1, 0],
  min: -30, max: 120, default: 25,
});
return arm;
```

```ts
joint(name: string, shape: Shape, pivot: [ number, number, number ], opts?: RevoluteJointOpts): Shape
```

`RevoluteJointOpts`: `{ axis?: [ number, number, number ], min?: number, max?: number, default?: number, unit?: string, reverse?: boolean }`

---

## Classes

### `Assembly`

Container for a kinematic mechanism made up of named parts and joints.

An assembly is a directed graph where **parts** are nodes and **joints** are directed edges from parent to child. The graph must be a forest (one or more trees with no cycles). Root parts (no incoming joint) are fixed to world space.

Each joint carries a `frame` transform (from the parent part frame to the joint's zero-state frame) and a motion formula:

```
childWorld = parentWorld × frame × motion(value) × childBase
```

Three joint types are supported:

- **revolute** — rotates the child around an axis by `value` degrees
- **prismatic** — translates the child along an axis by `value` mm
- **fixed** — no motion; rigidly attaches the child at `frame`

**Quick start**

```ts
const mech = assembly("Arm")
  .addPart("base", box(80, 80, 20).translate(0, 0, -10))
  .addPart("link", box(140, 24, 24).translate(0, -12, -12))
  .addJoint("shoulder", "revolute", "base", "link", {
    axis: [0, 1, 0],
    min: -30, max: 120, default: 25,
    frame: Transform.identity().translate(0, 0, 20),
  });

return mech; // auto-solved at defaults
```

Returning an unsolved `Assembly` auto-solves at default joint values. Return a `SolvedAssembly` directly for a specific pose:

```ts
return mech.solve({ shoulder: 60 });
```

**Return types**

| Return value | Standalone | `require()` result type |
|---|---|---|
| `Assembly` (unsolved) | yes | `ImportedAssembly` |
| `SolvedAssembly` | yes | `SolvedAssembly` |

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `name` | `string` | — |

**Connectors**

#### `usedConnectorRefs()` — Connector refs (e.g. "PartName.connectorName") consumed by connect/match calls.

```ts
get usedConnectorRefs(): ReadonlySet<string>
```

#### `withConnectors()` — Attach named connectors to a specific part or the assembly as a whole.

Connectors declared this way are in the part's local coordinate system. They are captured automatically if the incoming [`Shape`](/docs/core#shape) already has connectors via `shape.withConnectors(...)`, but you can also add or override connectors after the fact with this method.

Use the single-argument overload to attach assembly-level connectors — these are exposed when this assembly is imported as a sub-assembly.

```ts
withConnectors(partName: string, connectors: Record<string, ConnectorInput>): Assembly
```

#### `getConnectors()` — Get connectors declared on a part in part-local space.

```ts
getConnectors(partName: string): ConnectorMap
```

#### `getConnector()` — Parse a "PartName.connectorName" reference and return the resolved connector. Throws descriptive errors if the part or connector doesn't exist.

```ts
getConnector(ref: string): { partName: string; connectorName: string; connector: ConnectorDef; }
```

#### `connect()` — Connect two parts by aligning their declared connectors, automatically computing frame and axis.

Connector references use `"PartName.connectorName"` format. The system aligns connector origins (child connector lands exactly on parent connector) and derives the joint frame and axis from the connector geometry — no manual `frame` or `axis` math needed.

**Face-to-face convention:** Connectors always meet face-to-face, like a USB plug meeting a socket. Each connector's axis points "outward" from its part. When two connectors mate, the system brings them together so their axes oppose (anti-parallel). This is the same convention used by `matchTo()`.

For a revolute joint (hinge), both connectors' axes should point outward from their respective parts along the hinge line. For a prismatic joint (slider), both axes should point along the slide direction from their part's perspective.

The joint type is inferred from the connector's `kind` field if not specified in `options`.

When connectors are defined with `start`/`end`, you can control which point on each connector meets via `align` / `parentAlign` / `childAlign` (`'start'`, `'middle'`, `'end'`).

Use `connect()` when connector origins must physically coincide (flange-to-flange, bolt-into-bore). For mechanisms where parts share an axis but are deliberately spaced apart, use `addRevolute()` with pre-positioned parts instead.

```ts
// Hinge: both axes point outward along the hinge line
const frame = box(100, 10, 80).withConnectors({
  hinge: connector("hinge", { origin: [0, 0, 40], axis: [0, 0, 1] }),
});
const door = box(60, 4, 80).withConnectors({
  hinge: connector("hinge", { origin: [0, 0, 40], axis: [0, 0, -1] }),
});
assembly("Door")
  .addPart("Frame", frame)
  .addPart("Door", door)
  .connect("Frame.hinge", "Door.hinge", { as: "swing", min: 0, max: 110 });
```

```ts
connect(parentConnectorRef: string, childConnectorRef: string, options?: ConnectOptions): Assembly
```

#### `match()` — Auto-create a joint by matching typed connectors between two parts.

Connectors can carry a `connectorType` string and a `gender` (`'male'`, `'female'`, or `'neutral'`). `match()` validates type and gender compatibility (use `{ force: true }` to skip validation) and creates the joint automatically from the connector's `kind` metadata.

The `pairs` map is `{ childConnector: parentConnector }`. The first pair drives joint creation; additional pairs are validated but do not create additional joints (they constrain the same rigid connection).

Define connectors on shapes with `shape.withConnectors(...)`:

```ts
const door = doorShape.withConnectors({
  hinge_top: connector.male("hinge", { origin: [0, 0, 90], axis: [0, 0, 1] }),
  hinge_bottom: connector.male("hinge", { origin: [0, 0, 10], axis: [0, 0, 1] }),
});
```

Then match in the assembly:

```ts
const mech = assembly("Door")
  .addPart("Frame", frame)
  .addPart("Door", door)
  .match("Door", "Frame", { hinge_top: "hinge_top", hinge_bottom: "hinge_bottom" });
// Revolute connectors → auto-creates revolute joint. No manual addRevolute needed.
```

```ts
match(childPartName: string, parentPartName: string, pairs: Record<string, string>, options?: MatchToOptions & { as?: string; }): Assembly
```

**References**

#### `withReferences()` — Attach named placement reference points to this assembly. These are surfaced automatically on the ImportedAssembly when this file is imported via require(), so consumers can use placeReference() without re-declaring them. Returns a new Assembly — does not mutate.

```ts
withReferences(refs: Pick<PlacementReferenceInput, "points">): Assembly
```

**Solving**

#### `solve()` — Solve the assembly at the given joint state and return positioned parts.

Performs a depth-first traversal of the joint graph. Each joint's value is taken from `state`, falling back to `defaultValue`. Coupled joints compute their value from source joints. Values outside `[min, max]` are clamped (a warning is added to `SolvedAssembly.warnings()`).

If mate constraints were registered via `mate()`, the solver runs a pre-pass to derive base transforms, then the kinematic DFS applies joints on top of those positions.

**Pitfall — [`jointsView`](/docs/viewport#jointsview) double-rotation:** When calling `toJointsView()`, always solve at the rest pose (all joint values = 0 or default). Solving at a non-zero angle and then animating will double-rotate parts. Use the `defaults` option on `toJointsView()` to set the initial display angle instead.

This pitfall only applies when `toJointsView()` is active. If you only want a static posed result, return the solved assembly directly and skip `toJointsView()`.

**Example — static posed output (no `toJointsView()`)**

```ts
return mech.solve({ shoulder: 45, elbow: -20 });
```

```ts
solve(state?: JointState): SolvedAssembly
```

**Other**

#### `mate()` — Register mate constraints between parts. Constraints are solved during `solve()` to derive part positions and explode hints. Part references use "partName:featureName" format.

```ts
mate(fn: (m: MateBuilder) => void): Assembly
```

#### `addFrame()` — Add a virtual reference frame (no geometry) to the assembly graph.

Useful when you need a named pivot point or coordinate frame that has no visual geometry. Acts like a zero-volume part and can be connected to other parts via joints.

```ts
addFrame(name: string, options?: PartOptions): Assembly
```

#### `addPart()` — Add a named part to the assembly.

Connectors declared on the part (via `withConnectors()`) are captured automatically. Parts are positioned at world origin by default unless a `transform` is provided in `options`. For root parts (no incoming joint), `transform` is their final world position.

When a part is a [`ShapeGroup`](/docs/core#shapegroup), name the group children explicitly to get readable viewport labels (e.g. `"Base Assembly.Body"` instead of `"Base Assembly.1"`):

```ts
const housing = group(
  { name: "Body", shape: body },
  { name: "Lid", shape: lid },
);
assembly.addPart("Base Assembly", housing);
```

```ts
addPart(name: string, part: AssemblyPart, options?: PartOptions): Assembly
```

#### `addJoint()` — Add a kinematic joint between a parent and child part.

`frame` is a transform from the **parent part frame** to the **joint frame at zero state**. The child's world position is computed as:

```
childWorld = parentWorld × frame × motion(value) × childBase
```

For revolute joints `value` is in degrees; for prismatic joints `value` is in mm. Coupled joints (see `addJointCoupling`) ignore the `state` value passed to `solve()` and compute their value from source joints.

```ts
addJoint(name: string, type: JointType, parent: string, child: string, options?: JointOptions): Assembly
```

#### `addRevolute()` — Shorthand for `addJoint(name, 'revolute', parent, child, options)`.

```ts
addRevolute(name: string, parent: string, child: string, options?: JointOptions): Assembly
```

#### `addPrismatic()` — Shorthand for `addJoint(name, 'prismatic', parent, child, options)`.

```ts
addPrismatic(name: string, parent: string, child: string, options?: JointOptions): Assembly
```

#### `addFixed()` — Shorthand for `addJoint(name, 'fixed', parent, child, options)`.

Fixed joints rigidly attach a child part to its parent at `frame` with no motion. Before calling `mergeInto()`, use `addFixed()` to collapse multiple root parts into a single root.

```ts
addFixed(name: string, parent: string, child: string, options?: JointOptions): Assembly
```

#### `addJointCoupling()` — Link a joint's value to a linear combination of other joint values.

The driven joint's value is computed as:

```
driven = offset + Σ(ratio_i × source_i)
```

Coupled joints ignore any value passed in `solve(state)` — a warning is emitted if you try to override one. Coupling cycles are rejected. You cannot sweep a coupled joint directly; sweep one of its source joints instead.

```ts
assembly
  .addRevolute("Steering", "Base", "Turret", { axis: [0, 0, 1] })
  .addRevolute("WheelDrive", "Turret", "Wheel", { axis: [1, 0, 0] })
  .addRevolute("TopGear", "Base", "TopInput", { axis: [0, 0, 1] })
  .addJointCoupling("TopGear", {
    terms: [
      { joint: "Steering", ratio: 1 },
      { joint: "WheelDrive", ratio: 20 / 14 },
    ],
  });
```

```ts
addJointCoupling(jointName: string, options: JointCouplingOptions): Assembly
```

#### `addGearCoupling()` — Link two revolute joints via a gear ratio.

Choose exactly one ratio source:

- `ratio` — explicit numeric ratio (driven/driver, negative for external mesh)
- `pair` — a `GearRatioLike` from `lib.gearPair`, `lib.bevelGearPair`, etc. (uses `pair.jointRatio`)
- `driverTeeth` + `drivenTeeth` — auto-computes ratio; use `mesh` to control sign (`'external'` = negative/opposite rotation, `'internal'` = positive, `'bevel'`/`'face'` = negative)

When `pair` carries a `phaseDeg`, it is auto-applied as the coupling `offset` to align teeth correctly. Override with `offset: 0` if gear shapes already have the phase baked in.

```ts
const pair = lib.gearPair({ pinion: { module: 1.25, teeth: 14 }, gear: { module: 1.25, teeth: 42 } });
assembly
  .addRevolute("Pinion", "Base", "PinionPart", { axis: [0, 0, 1] })
  .addRevolute("Driven", "Base", "GearPart", { axis: [0, 0, 1] })
  .addGearCoupling("Driven", "Pinion", { pair });
```

```ts
addGearCoupling(drivenJointName: string, driverJointName: string, options?: GearCouplingOptions): Assembly
```

#### `sweepJoint()` — Sample a joint through its motion range, collecting collision data at each step.

Divides `[from, to]` into `steps` intervals (producing `steps + 1` frames). At each sample, the assembly is solved with the sweeping joint at that value and `baseState` for all others. Returns one `JointSweepFrame` per sample with the joint value, collision findings, and any solve warnings.

You cannot sweep a coupled joint — sweep one of its source joints instead.

```ts
const sweep = mech.sweepJoint("elbow", -10, 135, 12, { shoulder: 35 });
const hits = sweep.filter(frame => frame.collisions.length > 0);
console.log(`Collisions at ${hits.length} of ${sweep.length} poses`);
```

```ts
sweepJoint(jointName: string, from: number, to: number, steps: number, baseState?: JointState, collisionOptions?: CollisionOptions): JointSweepFrame[]
```

#### `toJointsView()` — Derive viewport joint controls from the assembly graph and register them.

Solves the assembly at rest (all joints = default), then converts each joint into a `JointViewInput` with world-space pivot and axis. Fixed joints become hidden zero-range revolute entries so attached parts follow their parent during animation. Joint couplings are forwarded to the viewport automatically.

This method is optional. Call it only when you want viewport joint sliders, coupled controls, or playback animations. If you only want geometry, return the `Assembly` or `SolvedAssembly` directly and skip `toJointsView()`.

**Critical pitfall:** Always call `toJointsView()` before solving for display. Then solve at the **rest pose** (no state overrides) and return that solved assembly result directly. Do not flatten it with `.toGroup()` if you want the viewport joint animation to keep working.

Do not solve at a non-zero angle when using `toJointsView()` — the viewport will apply the same rotation again, double-rotating the part.

```ts
mech.toJointsView({
  defaults: { J1: 30 },
  animations: [{
    name: "Swing", duration: 2, loop: true,
    keyframes: [{ values: { J1: -45 } }, { values: { J1: 45 } }, { values: { J1: -45 } }],
  }],
});

// Solve at REST — viewport handles posing
return mech.solve();
```

```ts
toJointsView(options?: ToJointsViewOptions): void
```

#### `describe()` — Return the serializable assembly definition used by solve/inspect pipelines.

```ts
describe(): AssemblyDefinition
```

**Legacy Aliases**

- `usedPortRefs` -> `usedConnectorRefs`
- `withPorts()` -> `withConnectors()`
- `getPorts()` -> `getConnectors()`
- `getPort()` -> `getConnector()`

### `ImportedAssembly`

A wrapper around an imported `Assembly` that provides kinematic access and convenient transform helpers.

When a `.forge.js` file returns an unsolved `Assembly`, [`require()`](/docs/core#require) wraps it in an `ImportedAssembly`. This preserves the kinematic structure — you can call `solve()`, `sweepJoint()`, and `mergeInto()` — while also allowing convenience transforms that auto-solve at default values.

**Kinematic access**

```ts
const arm = require("./arm.forge.js");

const solved = arm.solve({ shoulder: 45 });   // full kinematic solve
const link   = arm.part("Link", { shoulder: 60 }); // single part at state
const group  = arm.toGroup({ shoulder: 45 });  // only when ShapeGroup behavior is needed
```

**Convenience transforms** (auto-solve at defaults, return [`ShapeGroup`](/docs/core#shapegroup)):

```ts
const positioned = arm.rotateZ(-90).translate(0, -20, 50);
```

**Merging into a parent**

```ts
require("./arm.forge.js").mergeInto(robot, {
  prefix: "Left Arm",
  mountParent: "Chassis",
  mountJoint: "leftMount",
  mountOptions: { frame: Transform.identity().translate(-70, 0, 10) },
});
```

#### `assembly()` — The underlying Assembly — use for sweepJoint, addPart into parent, etc.

```ts
get assembly(): Assembly
```

#### `solve()` — Solve the assembly at the given joint state (defaults to each joint's default value).

```ts
solve(state?: JointState): SolvedAssembly
```

#### `part()` — Return a specific named part positioned at the given joint state, with any stored placement offset applied.

```ts
part(name: string, state?: JointState): AssemblyPart
```

#### `toGroup()` — Convert all assembly parts to a ShapeGroup with named children. Use this for composition, transforms, or child lookup — not as a required render step for assemblies. Child names match the part names used in the assembly. Any stored placement offset and placement references are forwarded to the group.

```ts
toGroup(state?: JointState): ShapeGroup
```

#### `withReferences()` — Attach named placement reference points to this assembly. Points are simple 3D coordinates (relative to the assembly's own origin). Returns a new ImportedAssembly — does not mutate.

```ts
withReferences(refs: Pick<PlacementReferenceInput, "points">): ImportedAssembly
```

#### `referenceNames()` — List all attached placement reference names.

```ts
referenceNames(kind?: PlacementReferenceKind): string[]
```

#### `placeReference()` — Translate the assembly so the named reference point lands on `target`. Returns a new ImportedAssembly — does not mutate. All point refs are translated by the same delta.

```ts
placeReference(ref: string, target: [ number, number, number ], offset?: [ number, number, number ]): ImportedAssembly
```

#### `translate()` — Solve at defaults and return a translated ShapeGroup.

```ts
translate(x: number, y: number, z: number): ShapeGroup
```

#### `rotate()` — Solve at defaults and return a rotated ShapeGroup.

```ts
rotate(axis: [ number, number, number ], angleDeg: number, options?: { pivot?: [ number, number, number ]; }): ShapeGroup
```

#### `rotateX()` — Solve at defaults and return a ShapeGroup rotated around X.

```ts
rotateX(angleDeg: number, options?: { pivot?: [ number, number, number ]; }): ShapeGroup
```

#### `rotateY()` — Solve at defaults and return a ShapeGroup rotated around Y.

```ts
rotateY(angleDeg: number, options?: { pivot?: [ number, number, number ]; }): ShapeGroup
```

#### `rotateZ()` — Solve at defaults and return a ShapeGroup rotated around Z.

```ts
rotateZ(angleDeg: number, options?: { pivot?: [ number, number, number ]; }): ShapeGroup
```

#### `scale()` — Solve at defaults and return a scaled ShapeGroup.

```ts
scale(v: number | [ number, number, number ]): ShapeGroup
```

#### `mirror()` — Solve at defaults and return a mirrored ShapeGroup.

```ts
mirror(normal: [ number, number, number ]): ShapeGroup
```

#### `color()` — Solve at defaults and return a colored ShapeGroup.

```ts
color(hex: string): ShapeGroup
```

#### `child()` — Solve at defaults, get a named child part from the resulting group.

```ts
child(name: string): Shape | Sketch | ShapeGroup
```

#### `mergeInto()` — Flatten this sub-assembly's parts and joints into `parent` and wire a mount joint.

All part and joint names from the sub-assembly are prefixed with `"${options.prefix}."` to avoid collisions. After the merge, sub-assembly joints are driven from the parent using the prefixed names:

```ts
parent.solve({ "Left Arm.shoulder": 45, "Right Arm.shoulder": -20 })
```

Joint couplings inside the sub-assembly are preserved and rewritten with the prefix. Ports from sub-assembly parts are forwarded with the prefix.

The sub-assembly must have exactly one root part. If it has multiple roots, use `addFixed()` first to consolidate them before merging.

```ts
const robot = assembly("Robot").addPart("Chassis", chassis);

require("./arm.forge.js").mergeInto(robot, {
  prefix: "Left Arm",
  mountParent: "Chassis",
  mountJoint: "leftMount",
  mountOptions: { frame: Transform.identity().translate(-70, 0, 10) },
});
```

```ts
mergeInto(parent: Assembly, options: MergeIntoOptions): Assembly
```

### `SolvedAssembly`

The result of solving an assembly at a specific joint state.

`SolvedAssembly` holds world-space transforms for every part at a given pose. Top-level scripts can return a `SolvedAssembly` directly for display. Use `toGroup()` when you specifically need a [`ShapeGroup`](/docs/core#shapegroup) for composition, group-style transforms, or named-child lookup. Do not call `toGroup()` just to make a solved assembly render. Use `getPart()` / `getTransform()` to inspect individual parts programmatically.

**Validation**

Call `collisionReport()` to detect overlapping parts, or `sweepJoint()` on the parent `Assembly` to check for interference across the joint's motion range.

```ts
const solved = mech.solve({ shoulder: 45, elbow: -20 });
console.log("Collisions", solved.collisionReport());
return solved;
```

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `name` | `string` | — |

**Methods:**

#### `warnings()` — Return any warnings generated during solve (clamped joints, unconverged mates, etc.).

```ts
warnings(): string[]
```

#### `getJointState()` — Return a snapshot of resolved joint values (after clamping and coupling).

```ts
getJointState(): JointState
```

#### `mateExplodeHints()` — Explode direction hints derived from mate constraints, or null if no mates.

```ts
get mateExplodeHints(): Record<string, { direction: Vec3; }> | null
```

#### `mateDof()` — Remaining degrees of freedom after mate constraints, or null if no mates.

```ts
get mateDof(): number | null
```

#### `mateConverged()` — Whether the mate constraint solver converged, or null if no mates.

```ts
get mateConverged(): boolean | null
```

#### `getTransform()` — Return the world-space [`Transform`](/docs/core#transform) for the named part at the solved pose.

```ts
getTransform(partName: string): Transform
```

#### `getPart()` — Return the named part already positioned at its solved world transform.

```ts
getPart(partName: string): AssemblyPart
```

#### `toGroup()` — Convert all solved parts into a [`ShapeGroup`](/docs/core#shapegroup) with named children.

Each part becomes a named child in the group, already positioned at its solved world transform. Use this only when you specifically need a [`ShapeGroup`](/docs/core#shapegroup) for composition, [`ShapeGroup`](/docs/core#shapegroup) transforms, or named-child access. Top-level scripts can return the `SolvedAssembly` directly; do not call `toGroup()` just to make a solved assembly render.

```ts
const armGroup = mech.solve({ shoulder: 60 }).toGroup(); // only because we need rotateZ()
return armGroup.rotateZ(90);
```

```ts
toGroup(): ShapeGroup
```

#### `toSceneObjects()` — Return an array of named scene objects for the viewport renderer.

Each part becomes `{ name, shape }` or `{ name, group: [...] }` if the part is a [`ShapeGroup`](/docs/core#shapegroup). Top-level scripts should normally return the `SolvedAssembly` directly. Use `toGroup()` when you need [`ShapeGroup`](/docs/core#shapegroup) behavior; use this method only for advanced scene-graph control where you need access to the flat per-part array with metadata.

```ts
toSceneObjects(): Array<{ name: string; shape?: Shape; group?: Array<{ name: string; shape: Shape; tags?: string[]; }>; metadata?: PartMetadata; }>
```

#### `toScene()` — Backward-compatible alias for `toSceneObjects()`.

```ts
toScene(): Array<{ name: string; shape?: Shape; group?: Array<{ name: string; shape: Shape; tags?: string[]; }>; metadata?: PartMetadata; }>
```

#### [`bom()`](/docs/output#bom) — Generate a bill of materials for all parts in the solved assembly.

```ts
bom(): BomRow[]
```

#### `bomCsv()` — Generate a bill of materials as a CSV string.

```ts
bomCsv(): string
```

#### `collisionReport()` — Detect overlapping (colliding) part pairs in this solved pose.

Computes boolean intersections between all part pairs and returns findings where the overlap volume exceeds `minOverlapVolume` (default 0.1 mm³).

```ts
const solved = mech.solve({ shoulder: 35, elbow: 60 });
console.log("Collisions", solved.collisionReport());
```

```ts
collisionReport(options?: CollisionOptions): CollisionFinding[]
```

#### `minClearance()` — Compute the minimum gap (clearance) between two parts in this solved pose.

Returns `0` if the parts are touching or overlapping. Requires the Manifold backend. `searchLength` bounds the search radius in mm — increase it for widely separated parts.

```ts
minClearance(partA: string, partB: string, searchLength?: number): number
```

### `MateBuilder`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `constraints` | `Constraint3D[]` | — |

**Methods:**

#### `flush()` — Constrain two faces so they stay flush.

```ts
flush(faceA: string, faceB: string): string
```

#### `align()` — Constrain two faces so their normals align.

```ts
align(faceA: string, faceB: string): string
```

#### `parallel()` — Constrain two faces so they remain parallel.

```ts
parallel(faceA: string, faceB: string): string
```

#### `faceDistance()` — Constrain the distance between two faces.

```ts
faceDistance(faceA: string, faceB: string, distance: number): string
```

#### `concentric()` — Constrain two axes to share the same center line.

```ts
concentric(axisA: string, axisB: string): string
```

#### `axisParallel()` — Constrain two axes to remain parallel.

```ts
axisParallel(axisA: string, axisB: string): string
```

#### `pointCoincident()` — Constrain two points to coincide.

```ts
pointCoincident(pointA: string, pointB: string): string
```

#### `pointOnFace()` — Constrain a point to lie on a face.

```ts
pointOnFace(point: string, face: string): string
```

#### `pointOnAxis()` — Constrain a point to lie on an axis.

```ts
pointOnAxis(point: string, axis: string): string
```

#### `angle()` — Constrain the angle between two faces.

```ts
angle(faceA: string, faceB: string, degrees: number): string
```

#### `totalEquations()` — Total constraint equations.

```ts
get totalEquations(): number
```

---

<!-- generated/sheet-metal.md -->

# Sheet Metal

Folded sheet metal parts with flanges, bends, and flat pattern unfolding.

## Contents

- [Sheet Metal](#sheet-metal) — `sheetMetal`
- [Laser Cutting](#laser-cutting) — `kerfCompensateOutline`, `kerfCompensateTabs`, `kerfCompensateSlots`, `kerfCompensatePart`, `lookupKerf`, `flatPanel`, `flatPart`, `fingerJoint`, `tabSlot`, `assemblyPreview`, `assemblyInstructions`, `formatInstructions`, `laserKit`
- [SheetMetalPart](#sheetmetalpart)
- [FlatPart](#flatpart)
- [LaserKit](#laserkit)
- [SHEET_METAL_EDGES](#sheet-metal-edges)
- [COMMON_KERFS](#common-kerfs)

## Functions

### Sheet Metal

#### `sheetMetal()` — Create a parametric sheet metal part with flanges, bend allowances, and flat-pattern unfolding.

`sheetMetal()` keeps one semantic model and derives both a folded 3D solid and an accurate flat pattern from it. The K-factor bend allowance is applied during unfolding. This is a strict v1 subset — it does not infer sheet metal from arbitrary solids.

**Recommended authoring order:**

1. Define the base panel + thickness + bend parameters.
2. Chain `.flange()` calls for each edge. Validate with `.folded()` and `.flatPattern()` before adding cutouts.
3. Add panel cutouts, then flange cutouts one region at a time.
4. Validate after each new cutout region.

**v1 limitations:** one base panel, up to four 90° edge flanges, constant thickness, explicit K-factor, rectangular corner reliefs, planar cutouts only. No hems, jogs, lofted bends, non-90° flanges, or bend-region cutouts.

```ts
const cover = sheetMetal({
  panel: { width: 180, height: 110 },
  thickness: 1.5,
  bendRadius: 2,
  bendAllowance: { kFactor: 0.42 },
  cornerRelief: { size: 4 },
})
  .flange('top',    { length: 18 })
  .flange('right',  { length: 18 })
  .flange('bottom', { length: 18 })
  .flange('left',   { length: 18 })
  .cutout('panel', rect(72, 36), { selfAnchor: 'center' })
  .cutout('flange-right', roundedRect(26, 10, 5), { selfAnchor: 'center' });

const folded = cover.folded();
const flat   = cover.flatPattern();
```

```ts
sheetMetal(options: SheetMetalOptions): SheetMetalPart
```

**`SheetMetalOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `panel` | `{ width: number; height: number; }` | Base panel dimensions. This is the flat blank before flanges are applied. |
| `thickness` | `number` | Sheet thickness in mm. Applied uniformly across the panel and all flanges. |
| `bendRadius` | `number` | Inside bend radius in mm. Must be ≥ 0. Typically 0.5–2× the sheet thickness. |
| `bendAllowance` | `{ kFactor: number; }` | Bend allowance model used when computing the flat-pattern developed length. Currently only K-factor is supported. The K-factor (0–1) describes how far the neutral axis sits from the inner bend surface. Typical values: - Soft materials / large radius: 0.50 - General sheet steel: 0.42–0.44 - Hard materials / tight radius: 0.30–0.38 |
| `cornerRelief?` | `{ kind?: "rect"; size: number; }` | Corner relief cut at each bend intersection. Prevents material overlap when two flanges meet at a corner. Defaults to a rectangular relief sized to `bendRadius + thickness` if omitted. |

### Laser Cutting

#### `kerfCompensateOutline()` — Apply kerf compensation to a complete part outline (outer boundary + holes).

Offsets inward by half-kerf: the outer boundary shrinks and inner holes grow. This is correct because the laser beam removes material on both sides of the cut line.

```ts
kerfCompensateOutline(sketch: Sketch, kerf: number): Sketch
```

#### `kerfCompensateTabs()` — Apply kerf compensation to joint protrusions (tabs, fingers).

These grow by half-kerf so they are slightly oversized and fit tightly in their mating slots after the laser removes material.

```ts
kerfCompensateTabs(sketch: Sketch, kerf: number): Sketch
```

#### `kerfCompensateSlots()` — Apply kerf compensation to joint cutouts (slots, holes that receive tabs).

These grow by half-kerf so tabs can fit into them after the laser removes material from both sides of the slot walls.

```ts
kerfCompensateSlots(sketch: Sketch, kerf: number): Sketch
```

#### `kerfCompensatePart()` — Build a kerf-compensated part profile.

1. Start with the base profile.
2. Kerf-compensate each tab addition (grow by kerf/2), then union with base.
3. Kerf-compensate each slot subtraction (grow by kerf/2), then subtract from base.
4. Kerf-compensate the resulting outline (shrink by kerf/2).

Order matters: joints modify geometry BEFORE outline compensation so the final inward offset applies uniformly to the assembled profile.

```ts
kerfCompensatePart(baseProfile: Sketch, joints: PartJoints, kerf: number): Sketch
```

**`PartJoints`**
- `additions?: Sketch[]` — Geometry to ADD to the base profile (tabs, fingers protruding from edges).
- `subtractions?: Sketch[]` — Geometry to SUBTRACT from the base profile (slots, holes for mating tabs).

#### `lookupKerf()` — Look up kerf for a material + thickness + laser combo.

If `laserType` is omitted, returns the first matching material + thickness entry. Returns `undefined` when no match is found.

```ts
lookupKerf(material: string, thickness: number, laserType?: string): number | undefined
```

#### `flatPanel()` — Create a rectangular flat panel with 4 named edges.

Profile origin at bottom-left corner. Edges: bottom (y=0), right (x=width), top (y=height), left (x=0). Edge traversal follows CCW winding order.

```ts
flatPanel(name: string, width: number, height: number, thickness: number, options?: FlatPartOptions): FlatPart
```

`FlatPartOptions`: `{ material?: string, qty?: number, color?: string }`

#### `flatPart()` — Create a flat part from an arbitrary profile with user-named edges.

Edge normals are computed automatically (perpendicular to direction, rotated 90deg CW).

```ts
flatPart(name: string, profile: Sketch, thickness: number, edges?: Record<string, { start: [ number, number ]; end: [ number, number ]; }>, options?: FlatPartOptions): FlatPart
```

#### `fingerJoint()` — Connect two parts with finger joints along specified edges.

Adds finger geometry to partA's edge, cuts matching slots from partB's edge. The joint profiles are positioned along each edge using rotation + translation.

```ts
fingerJoint(partA: FlatPart, edgeNameA: string, partB: FlatPart, edgeNameB: string, options?: FingerJointOptions & { foldAngle?: number; }): void
```

**`FingerJointOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `fingers?` | `number` | Explicit finger count (must be odd, >= 3). Default: auto from length/thickness. |
| `fingerWidth?` | `number` | Explicit finger width. Default: auto. |
| `clearance?` | `number` | Extra clearance per side (mm). Default: 0. |
| `kerf?` | `number` | Laser kerf (mm). Default: 0. |
| `endStyle?` | `"full" \| "half"` | Whether edge starts with full finger or half. Default: 'full'. |

#### `tabSlot()` — Connect two parts with tab-and-slot joints along specified edges.

Adds tab geometry to partA's edge, cuts matching slots from partB's edge.

```ts
tabSlot(partA: FlatPart, edgeNameA: string, partB: FlatPart, edgeNameB: string, options?: TabSlotOptions & { foldAngle?: number; }): void
```

**`TabSlotOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `tabCount?` | `number` | Number of tabs. Default: auto (length / (4 * thickness)). |
| `tabWidth?` | `number` | Tab width. Default: 2 * thickness. |
| `clearance?` | `number` | Extra clearance per side (mm). Default: 0. |
| `kerf?` | `number` | Laser kerf (mm). Default: 0. |
| `inset?` | `number` | Distance from panel edges to first/last tab center. Default: thickness. |

#### `assemblyPreview()` — Generate a 3D assembly preview from flat parts and their joint records.

The preview can fold joints partially or fully and optionally apply exploded spacing so part relationships are easier to inspect visually.

```ts
assemblyPreview(parts: FlatPart[], joints: JointRecord[], options?: AssemblyPreviewOptions): AssemblyPreviewResult
```

**`JointRecord`**
- `foldAngle: number` — Fold angle in degrees. Default: 90.
- Also: `type: "finger" | "tabSlot" | "snapFit", partA: string, partB: string, edgeA: string, edgeB: string`

**`AssemblyPreviewOptions`**
- `kerf?: number` — Kerf compensation passed to each part's solid(). Default: 0
- `fold?: number` — Fold amount: 0 = flat layout, 1 = fully assembled. Default: 1
- `explode?: number` — Explode distance: 0 = assembled, >0 = parts spread outward. Default: 0

**`AssemblyPreviewResult`**
- `shapes: ShapeGroup` — All part shapes grouped for display.
- `partShapes: Map<string, Shape>` — Individual transformed shapes keyed by part name.

#### `assemblyInstructions()` — Generate step-by-step assembly instructions from flat parts and joints.

Algorithm:

1. Build adjacency graph from joints
2. Pick root part (most connections, or user-specified)
3. BFS from root, creating one step per part addition
4. Each step describes: which part to add, where it connects, how to orient it

Heuristics for step ordering:

- Start with the part that has the most connections (the base)
- Add parts that connect to already-assembled parts first (BFS order)
- Among candidates at the same BFS depth, prefer parts with more connections to already-assembled parts (structurally stable)

```ts
assemblyInstructions(parts: FlatPart[], joints: JointRecord[], options?: AssemblyInstructionsOptions): AssemblyInstructionsResult
```

**`AssemblyInstructionsOptions`**
- `rootPart?: string` — Part to start from. Default: part with most joint connections.

**`AssemblyInstructionsResult`**
- `totalParts: number` — Total number of parts in the assembly.
- `orphanParts: string[]` — Parts not connected to the joint graph (orphans).
- Also: `steps: AssemblyStep[]`

**`AssemblyStep`**

| Option | Type | Description |
|--------|------|-------------|
| `stepNumber` | `number` | 1-based step number. |
| `description` | `string` | Human-readable instruction. |
| `partName` | `string` | The part being added in this step. |
| `partNumber` | `number` | Part number (for cross-ref with cut sheets). |
| `connectsTo` | `string` | Which existing part it connects to. |
| `jointType` | `"finger" \| "tabSlot" \| "snapFit"` | Joint type used. |
| `newPartEdge` | `string` | The edge on the new part. |
| `existingPartEdge` | `string` | The edge on the existing part. |
| `foldAngle` | `number` | Fold angle in degrees. |
| `assembledParts` | `string[]` | Part names in the assembly so far (after this step). |

#### `formatInstructions()` — Format assembly instructions as a human-readable text document.

Includes a "Step 0" preamble identifying the base part, followed by numbered steps, and a note about any orphan parts.

```ts
formatInstructions(result: AssemblyInstructionsResult): string
```

#### `laserKit()` — Top-level factory for creating a LaserKit container.

```ts
laserKit(options?: LaserKitOptions): LaserKit
```

**`LaserKitOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `material?` | `string` | Default material label for parts that don't specify one. |
| `sheetWidth?` | `number` | Stock sheet width in mm (default 600). |
| `sheetHeight?` | `number` | Stock sheet height in mm (default 400). |
| `kerf?` | `number` | Laser kerf in mm (default 0.2). |

---

## Classes

### `SheetMetalPart`

An immutable sheet metal part that accumulates flanges and cutouts.

Each mutating method returns a **new** `SheetMetalPart`; the original is unchanged. The part does not produce geometry until you call `.folded()` or `.flatPattern()`.

#### `flange()` — Add a 90° flange along one edge of the base panel.

Each of the four edges (`'top'`, `'right'`, `'bottom'`, `'left'`) may carry at most one flange. Calling `.flange()` twice for the same edge throws.

Corner reliefs are automatically inserted at the intersections of adjacent flanges. Build flanges before cutouts — validate with `.folded()` and `.flatPattern()` after each addition.

```ts
const part = sheetMetal({ panel: { width: 100, height: 60 }, thickness: 1.5, bendRadius: 2, bendAllowance: { kFactor: 0.42 } })
  .flange('top', { length: 15 })
  .flange('bottom', { length: 15 });
```

```ts
flange(edge: SheetMetalEdge, options: SheetMetalFlangeOptions): SheetMetalPart
```

#### `cutout()` — Subtract a 2D sketch cutout from a planar region of the sheet metal part.

`region` must be `'panel'` or one of `'flange-top'`, `'flange-right'`, `'flange-bottom'`, `'flange-left'` (only available once the corresponding flange has been added). Cutouts inside bend regions are **not** supported in v1.

`sketch` must be an **unplaced** compile-covered 2D profile (e.g. the result of [`circle2d()`](/docs/sketch#circle2d), [`rect()`](/docs/sketch#rect), [`roundedRect()`](/docs/sketch#roundedrect)). Passing an already-placed sketch (one that has had `.onFace(...)` called on it) will throw.

**Authoring order:** Add all flanges before adding cutouts. Add panel cutouts before flange cutouts. Add one region at a time and validate with `.folded()` / `.flatPattern()` after each step.

```ts
const part = sheetMetal({ panel: { width: 180, height: 110 }, thickness: 1.5, bendRadius: 2, bendAllowance: { kFactor: 0.42 } })
  .flange('top', { length: 18 })
  .cutout('panel', rect(72, 36), { selfAnchor: 'center' })
  .cutout('flange-top', roundedRect(26, 10, 5), { selfAnchor: 'center' });
```

```ts
cutout(region: SheetMetalPlanarRegionName, sketch: Sketch, options?: SheetMetalCutoutOptions): SheetMetalPart
```

#### `regionNames()` — Return all semantic region names currently available on this part.

The returned list always includes `'panel'`. For every flange that has been added, the list also includes the corresponding `'flange-<edge>'` and `'bend-<edge>'` entries.

Use this to discover valid targets for `.cutout()` or for querying faces by region after materializing with `.folded()`.

Defended region names: `panel` | `flange-top` | `flange-right` | `flange-bottom` | `flange-left` | `bend-top` | `bend-right` | `bend-bottom` | `bend-left`

```ts
regionNames(): SheetMetalRegionName[]
```

#### `folded()` — Materialize the 3D folded solid.

Applies all flanges (bent up at their configured angles) and all registered cutouts, then returns the resulting [`Shape`](/docs/core#shape). The shape is compiler-owned and exact-exportable (STEP, IGES, etc.).

Prefer calling `.folded()` to validate each build step before proceeding to the final model.

```ts
folded(): Shape
```

#### `flatPattern()` — Materialize the flat-pattern (unfolded blank) for fabrication.

Unfolds all flanges using the K-factor bend allowance and lays the result flat in the XY plane. Cutouts are projected into the flat geometry. The returned shape is exact-exportable and ready for laser / waterjet / CNC nesting workflows.

The developed length of each bend zone is: `BA = (bendRadius + kFactor × thickness) × angleDeg × π / 180`

```ts
flatPattern(): Shape
```

### `FlatPart`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `name` | `string` | — |
| `thickness` | `number` | — |
| `options` | `FlatPartOptions` | — |

**Methods:**

#### `edges()` — All edges as a read-only map.

```ts
get edges(): ReadonlyMap<string, EdgeInfo>
```

#### `edge()` — Look up a named edge. Throws if the edge does not exist.

```ts
edge(name: string): EdgeInfo
```

#### `edgeNames()` — All edge names on this part.

```ts
edgeNames(): string[]
```

#### `partNumber()` — BOM part number assigned to this flat part.

```ts
get partNumber(): number
```

#### `joints()` — Joint records that attach this part to other parts in the kit.

```ts
get joints(): readonly JointRecord[]
```

#### `quantity()` — Requested quantity of this part in the kit. Defaults to `1`.

```ts
get quantity(): number
```

#### `addGeometry()` — Add geometry (e.g. protruding tabs) to the part profile.

```ts
addGeometry(sketch: Sketch): void
```

#### `subtractGeometry()` — Subtract geometry (e.g. slot cuts) from the part profile.

```ts
subtractGeometry(sketch: Sketch): void
```

#### `addJoint()` — Record a joint connection for assembly preview.

```ts
addJoint(record: JointRecord): void
```

#### `profile()` — Final 2D profile with joints and optional kerf compensation.

```ts
profile(kerf?: number): Sketch
```

#### `solid()` — 3D solid — extrude the profile by material thickness.

```ts
solid(kerf?: number): Shape
```

### `LaserKit`

#### `kerf()` — Laser kerf in mm.

```ts
get kerf(): number
```

#### `parts()` — All registered parts (flat, in insertion order).

```ts
get parts(): readonly FlatPart[]
```

#### `material()` — Default material label.

```ts
get material(): string
```

#### `sheetWidth()` — Stock sheet width in mm.

```ts
get sheetWidth(): number
```

#### `sheetHeight()` — Stock sheet height in mm.

```ts
get sheetHeight(): number
```

#### `addPart()` — Register a flat part with this kit. Assigns a sequential part number and records the quantity.

```ts
addPart(part: FlatPart, overrides?: { qty?: number; }): this
```

#### `cutSheets()` — Generate nested cut sheets using guillotine bin-packing.

```ts
cutSheets(): CuttingLayoutResult
```

#### [`bom()`](/docs/output#bom) — Bill of materials listing every part with dimensions.

```ts
bom(): LaserKitBomEntry[]
```

#### `partSvgs()` — Individual SVG string for each part profile, keyed by part name.

```ts
partSvgs(): Map<string, string>
```

#### `inventorySvg()` — Combined inventory SVG showing all parts in a labeled grid.

```ts
inventorySvg(): string
```

#### `assemblyPreview()` — 3D fold-up preview of the assembled kit.

```ts
assemblyPreview(options?: Omit<AssemblyPreviewOptions, "kerf">): AssemblyPreviewResult
```

#### `assemblyInstructions()` — Step-by-step assembly instructions.

```ts
assemblyInstructions(options?: AssemblyInstructionsOptions): AssemblyInstructionsResult
```

#### `formatInstructions()` — Human-readable assembly instructions text.

```ts
formatInstructions(options?: AssemblyInstructionsOptions): string
```

---

## Constants

### `SHEET_METAL_EDGES`

### `COMMON_KERFS`

Common kerf values. Users should always test-cut to verify for their specific setup.

---

<!-- generated/output.md -->

# Output & Annotations

Dimensions, BOM entries, verification checks, and sketch export.

## Contents

- [Annotations & Output](#annotations-output) — `bom`, `robotExport`, `dim`, `dimLine`
- [Sketch Export](#sketch-export) — `sketchToDxf`, `sketchToSvg`

## Functions

### Annotations & Output

#### `bom()` — Register a Bill of Materials entry for report export.

BOM entries are accumulated during script execution and exported alongside the model in report views. Rows are grouped by normalized `description + unit`. Pass an explicit `key` to force multiple descriptions to collapse into a single line item.

- `quantity` must be a finite number `>= 0`. A quantity of `0` is silently ignored (useful for conditional scripting with `param()`-driven counts).
- `unit` defaults to `"pieces"` when omitted or empty.
- The assembly `solved.bom()` / `solved.bomCsv()` API is separate and covers per-part assembly metadata; this function is for free-form purchased-item annotation.
- `bom()` is injected into every `.forge.js` script. Call it directly; do not write `const { bom } = require(...)`, because top-level declarations named `bom` collide with the built-in runtime name.

```ts
const tubeLen = param("Tube Length", 1200, { min: 300, max: 4000, unit: "mm" });
const boltCount = param("Bolt Count", 16, { min: 0, max: 200, integer: true });

bom(tubeLen, "iron tube 30 x 20", { unit: "mm" });
bom(boltCount, "M4 bolt, 16 mm length");
bom(4, "rubber foot", { key: "foot-rubber" }); // explicit aggregation key

// Structured metadata for richer reports:
bom(tubeLen, "rectangular steel tube", {
  unit: "mm",
  material: "steel",
  section: [30, 20],
  wall: 3,
});
```

```ts
bom(quantity: number, description: string, opts?: BomOpts): void
```

**`BomOpts`**

| Option | Type | Description |
|--------|------|-------------|
| `unit?` | `string` | Quantity unit label, e.g. "mm", "pieces", "kg". Default: "pieces" |
| `key?` | `string` | Optional explicit grouping key used during report aggregation. |
| `material?` | `string` | Material name, e.g. "steel", "birch plywood", "nylon" |
| `dimensions?` | `number[]` | Overall dimensions `[width, height]` or `[width, height, thickness]` in the entry's unit |
| `section?` | `number[]` | Cross-section dimensions `[w, h]` for tubes and profiles |
| `wall?` | `number` | Wall thickness for hollow sections (mm) |
| `diameter?` | `number` | Diameter for round stock, bolts, dowels (mm) |
| `length?` | `number` | Length for fasteners (mm) |
| `process?` | `string` | Manufacturing process, e.g. "laser cut", "CNC", "welded" |
| `notes?` | `string` | Free-form notes |
| `grain?` | `string` | Wood grain direction, e.g. "long", "cross" |

#### `robotExport()` — Declare that this script should export the assembly as a SDF/URDF robot package.

Call `robotExport()` alongside your assembly definition. The CLI commands `forgecad export sdf` and `forgecad export urdf` pick up the declaration and produce a robot package with:

- Mesh-based inertia tensors (full 6-component, not bounding-box approximations)
- Separate collision meshes (convex hull by default — ~50–80% smaller)
- Joint mimic elements derived from `addJointCoupling` / `addGearCoupling`

**Collision mesh modes** (set per-link via `links["PartName"].collision`):

| Mode | Description | Default |
|------|-------------|---------|
| `'convex'` | Convex hull (separate `_collision.stl`) | Yes |
| `'box'` | AABB primitive — fastest physics | |
| `'visual'` | Same mesh as visual — exact but slow | |
| `'none'` | No collision geometry | |

**Unit conventions:**

- Revolute `velocity` is in degrees/second in Forge; exporters convert to rad/s.
- Prismatic distances are in mm in Forge; exported in meters.
- `massKg` is preferred; `densityKgM3` is used when mass is unknown.
- Couplings with multiple terms: only the primary term (largest ratio) maps to `<mimic>` — SDF/URDF support single-leader mimic only. Dropped terms emit a warning.

```ts
const rover = assembly("Scout")
  .addPart("Chassis", box(300, 220, 50).translate(0, 0, -25))
  .addPart("Left Wheel", cylinder(30, 60, undefined, 48).translate(0, 0, -15))
  .addRevolute("leftWheel", "Chassis", "Left Wheel", {
    axis: [0, 1, 0],
    frame: Transform.identity().translate(90, 140, 60),
    effort: 20, velocity: 1080,
  });

robotExport({
  assembly: rover,
  modelName: "Scout",
  links: {
    Chassis: { massKg: 10 },
    "Left Wheel": { massKg: 0.8 },
  },
  plugins: {
    diffDrive: {
      leftJoints: ["leftWheel"], rightJoints: ["rightWheel"],
      wheelSeparationMm: 280, wheelRadiusMm: 60,
    },
  },
  world: { generateDemoWorld: true },
});
```

**CLI usage**

```bash
forgecad export sdf model.forge.js   # SDF package (Gazebo/Ignition)
forgecad export urdf model.forge.js  # URDF package (ROS/PyBullet/MuJoCo)
```

```ts
robotExport(options: RobotExportOptions): CollectedRobotExport
```

**`RobotExportOptions`**: `assembly: Assembly`, `modelName?: string`, `state?: JointState`, `static?: boolean`, `selfCollide?: boolean`, `allowAutoDisable?: boolean`, `links?: Record<string, RobotLinkExportOptions>`, `joints?: Record<string, RobotJointExportOptions>`, `plugins?: { diffDrive?: RobotDiffDrivePluginOptions; jointStatePublisher?: RobotJointStatePublisherOptions; }`, `world?: RobotWorldOptions`

`RobotLinkExportOptions`: `{ massKg?: number, densityKgM3?: number, collision?: "visual" | "convex" | "box" | "none" }`

`RobotJointExportOptions`: `{ effort?: number, velocity?: number, damping?: number, friction?: number }`

**`RobotDiffDrivePluginOptions`**: `leftJoints: string[]`, `rightJoints: string[]`, `wheelSeparationMm: number`, `wheelRadiusMm: number`, `topic?: string`, `odomTopic?: string`, `tfTopic?: string`, `frameId?: string`, `odomFrameId?: string`, `maxLinearVelocity?: number`, `maxAngularVelocity?: number`, `linearAcceleration?: number`, `angularAcceleration?: number`

`RobotJointStatePublisherOptions`: `{ enabled?: boolean, joints?: string[], topic?: string, updateRate?: number }`

`RobotWorldOptions`: `{ name?: string, generateDemoWorld?: boolean, spawnPose?: RobotPose6, keyboardTeleop?: RobotWorldKeyboardTeleopOptions }`

`RobotWorldKeyboardTeleopOptions`: `{ enabled?: boolean, linearStep?: number, angularStep?: number }`

**`CollectedRobotExport`**: `modelName: string`, `assembly: AssemblyDefinition`, `state: JointState`, `static: boolean`, `selfCollide: boolean`, `allowAutoDisable: boolean`, `links: Record<string, RobotLinkExportOptions>`, `joints: Record<string, RobotJointExportOptions>`, `plugins: { diffDrive?: RobotDiffDrivePluginOptions; jointStatePublisher?: RobotJointStatePublisherOptions; }`, `world: RobotWorldOptions | null`

`AssemblyDefinition`: `{ name: string, parts: AssemblyPartDef[], joints: AssemblyJointDef[], jointCouplings: AssemblyJointCouplingDef[] }`

`AssemblyPartDef`: `{ name: string, part: AssemblyPart, base: Transform, metadata?: PartMetadata }`

**`PartMetadata`**

| Option | Type | Description |
|--------|------|-------------|
| `tags?` | `string \| readonly string[]` | Viewport organization tags applied to scene objects produced from this part. |
| `material?`, `process?`, `tolerance?`, `qty?`, `notes?`, `densityKgM3?`, `massKg?` | | — |

**`AssemblyJointDef`**: `name: string`, `type: JointType`, `parent: string`, `child: string`, `frame: Transform`, `axis: Vec3`, `min?: number`, `max?: number`, `defaultValue: number`, `unit?: string`, `effort?: number`, `velocity?: number`, `damping?: number`, `friction?: number`, `connectorRefs?: JointConnectorRefs`

`JointConnectorRefs`: `{ parent: string, child: string, parentAlign?: PortAlign, childAlign?: PortAlign }`

`AssemblyJointCouplingDef`: `{ joint: string, terms: JointCouplingTermRecord[], offset: number }`

`JointCouplingTermRecord`: `{ joint: string, ratio: number }`

#### `dim()` — Add a dimension annotation between two points.

Dimension annotations are purely visual callouts rendered in the viewport and report export. They do not affect geometry or constrain the model.

Point arguments accept 2D tuples `[x, y]`, 3D tuples `[x, y, z]`, or [`Point2D`](/docs/sketch#point2d) objects (Z is treated as 0 for 2D inputs).

**Ownership Rules (Report Pages)**

- `currentComponent: true` — deterministic ownership by the calling import instance. Use when authoring reusable imported parts.
- `component: "Part Name"` — route dimension to another named returned object.
- Multiple owners: dimension is shared and appears on the assembly overview page.
- No ownership set: report export infers ownership via endpoint-in-bbox.

```ts
dim([-w / 2, 0, 0], [w / 2, 0, 0], { label: "Width" });
dim([0, 0, -h / 2], [0, 0, h / 2], { label: "Height", offset: 14 });
dim([0, 0, 0], [100, 0, 0], { component: "Base", color: "#00AAFF" });
```

`component` (string or string[] — report ownership), `currentComponent` (boolean)

```ts
dim(from: PointArg, to: PointArg, opts?: DimOpts): void
```

`DimOpts`: `{ offset?: number, label?: string, color?: string, component?: string | string[], currentComponent?: boolean }`

#### `dimLine()` — Add a dimension annotation along a [`Line2D`](/docs/sketch#line2d).

Convenience wrapper around { points from a constrained-sketch [`Line2D`](/docs/sketch#line2d) entity. All `opts` are forwarded unchanged.

```ts
const a = point(0, 0);
const b = point(100, 0);
dimLine(line(a, b), { label: "Span", offset: -8 });
```

```ts
dimLine(l: Line2D, opts?: DimOpts): void
```

### Sketch Export

#### `sketchToDxf()` — Export a 2D sketch as a DXF string (R12/AC1009 — maximally compatible).

For regular sketches, each polygon loop becomes a closed `LWPOLYLINE`. For constrained sketches, exports raw `LINE`, `CIRCLE`, and `ARC` entities from the constraint edge geometry, which preserves internal/shared edges that `toPolygons()` would merge away.

The R12 format is chosen for maximum compatibility with CAM tools, laser-cutter software, and older CAD readers.

```ts
const s = rect(100, 60);
const dxf = sketchToDxf(s, { layer: 'cut' });
```

```ts
sketchToDxf(sketch: Sketch, options?: SketchDxfOptions): string
```

**`SketchDxfOptions`**
- `layer?: string` — DXF layer name. Default: "0"
- `colorIndex?: number` — DXF color index (1–255, AutoCAD ACI). Default: 7 (white/black)

#### `sketchToSvg()` — Export a 2D sketch as an SVG string.

For regular sketches, exports filled polygon regions. For constrained sketches, exports raw edge geometry (LINE, ARC, CIRCLE) which preserves internal/shared edges that `toPolygons()` would merge away.

The SVG uses the sketch's native coordinate system (Y-up) with a CSS transform that flips Y so the output renders correctly in SVG's Y-down space. Coordinates are in sketch units (typically mm).

```ts
const s = rect(100, 60);
const svg = sketchToSvg(s, { stroke: '#333', strokeWidth: 0.8 });
```

```ts
sketchToSvg(sketch: Sketch, options?: SketchSvgOptions): string
```

**`SketchSvgOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `stroke?` | `string` | Stroke color. Default: "black" |
| `strokeWidth?` | `number` | Stroke width in sketch units. Default: 0.5 |
| `fill?` | `string` | Fill color. Default: "none" |
| `padding?` | `number` | Padding around the sketch bounding box in sketch units. Default: 2 |
| `pixelsPerUnit?` | `number` | If set, scale so 1 sketch-unit = this many px. Otherwise auto-fit. |

---

<!-- generated/lib.md -->

# Part Library

Pre-built fasteners, gears, pipes, structural profiles, and utility shapes. Access via `lib.*`.

## Contents

- [TangentLoop2D](#tangentloop2d)
- [DriveWheelBuilder](#drivewheelbuilder)
- [lib](#lib)

---

## Classes

### `TangentLoop2D`

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `circles` | `TangentCircle2D[]` | — |
| `mode` | `BeltMode` | — |
| `segments` | `BeltPathSegment[]` | — |
| `straightSpans` | `BeltLineSpan[]` | — |
| `wraps` | `BeltWrapArc[]` | — |
| `wrapByPulley` | `Record<string, BeltWrapArc>` | — |
| `length` | `number` | — |

**Methods:**

#### `toSketch()` — Convert the loop centerline into a thin visual sketch.

```ts
toSketch(width?: number): Sketch
```

#### `toProfile()` — Convert the loop into a filled profile using the pitch path itself as the boundary.

```ts
toProfile(): Sketch
```

#### `offsetBand()` — Build a belt band sketch by offsetting the route to inner and outer pulley radii.

```ts
offsetBand(thickness: number): Sketch
```

### `DriveWheelBuilder`

#### `addSpurTeethBetween()` — Add an involute spur-tooth window on part of the pitch circle.

```ts
addSpurTeethBetween(options: DriveWheelSpurTeethRegionOptions): this
```

#### `addSolidArcBetween()` — Add a constant-radius solid arc region such as a dwell, stop, or pusher.

```ts
addSolidArcBetween(options: DriveWheelSolidArcRegionOptions): this
```

#### `addShapeRegion()` — Add a fully custom region shape while preserving region metadata.

```ts
addShapeRegion(name: string, shape: Shape, options?: DriveWheelShapeRegionOptions): this
```

#### `build()` — Build the final wheel shape with a bore connector and region metadata.

```ts
build(): Shape
```

---

## Constants

### `lib`

Pre-built parametric parts available in user scripts as `lib.*`.

Every key in this object becomes a method or namespace on the `lib` object exposed to `.forge.js` scripts. The catalog includes:

**Fasteners and hardware patterns:** `bolt`, `nut`, `washer`, `fastenerSet`, `boltedServiceCover`, `datumEnclosureAssembly`, `snapLatchCoverAssembly`, `pinnedLeverAssembly`, `retainedShaftAssembly`, `capturedLinearSlide`, `capturedCartridgeGuideAssembly`, `livingHingeCoverAssembly`, `knuckledHingeAssembly`, `clevisPinJointAssembly`, `seatedBearingAssembly`, `cableGlandAnchorAssembly`, `hoseBarbPortAssembly`, `routedTubeClipAssembly`, `pcbTerminalBlockAssembly`, `thumbScrewClampAssembly`, `fastenerHole`, `boltHole`, `counterbore`, `hexNut`, `holePattern`

**Structure:** `tube`, `pipe`, `bracket`, `pipeRoute`, `elbow`, `tSlotProfile`, `tSlotExtrusion`, `profile2020BSlot6Profile`, `profile2020BSlot6`

**Belt drives:** `beltDrive`, `tangentLoop2d`

**Threads:** `thread`

**Gears:** `spurGear`, `sectorGear`, `driveWheel`, `bevelGear`, `faceGear`, `sideGear`, `ringGear`, `rackGear`, `gearPair`, `bevelGearPair`, `faceGearPair`, `sideGearPair`

**Gear bodies:** `gearBodies.disk`, `gearBodies.diskWithHub`, `gearBodies.spoked`, `gearBodies.fromProfile` plus direct aliases `gearBodyDisk`, `gearBodyDiskWithHub`, `gearBodySpoked`, `gearBodyFromProfile`

**Gear ratios (pure math helpers):** `gearRatio`, `rackRatio`, `planetaryRatio`

**Bolt patterns:** `boltPattern` — define hole positions once, cut them from multiple parts

**Utilities:** `explode`

Sizes outside the supported ranges will throw at runtime with a descriptive error.

- `boltHole(diameter: number, depth: number): Shape` — Simple cylindrical through-hole cutter centered on Z=0. Subtract the result from a part to produce a plain cylindrical clearance hole. For ISO metric sizes with fit classes and counterbore/countersink, use {
- `fastenerHole(opts: FastenerHoleOptions): Shape` — ISO metric fastener hole cutter with optional counterbore or countersink. **Details** Returns a cutter shape (subtract from a solid to produce the hole). Sizes outside M2–M10 will throw. Extend `METRIC_HOLE_TABLE` in this file to add new sizes. **Example** ```ts const plate = box(60, 40, 8) .subtract(lib.fastenerHole({ size: 'M5', fit: 'normal', depth: 8 }) .translate(15, 10, 4)); ```
- `counterbore(holeDia: number, boreDia: number, boreDepth: number, totalDepth: number): Shape` — Counterbore hole cutter — through-hole with a wider cylindrical recess at the top. Use for socket-head cap screws that must sit flush. Subtract from a solid. For ISO metric sizing and fit classes, prefer {
- `tube(outerX: number, outerY: number, outerZ: number, wall: number): Shape` — Rectangular hollow tube (thin-wall box section). Both the outer and inner boxes are centered on the XY plane with their base at Z=0.
- `pipe(height: number, outerRadius: number, wall: number, segments?: number): Shape` — Hollow cylindrical pipe. Centered on the XY plane, extending upward along +Z from z=0 to z=height. For complex routed pipe geometry, see `lib.pipeRoute`.
- `explode<T extends ExplodeItem[] | ShapeGroup>(items: T, options?: ExplodeOptions): T` — Apply deterministic exploded-view offsets to an assembly tree. **Details** Traverses arrays of shapes/sketches/named items, nested `{ name, group: [...] }` structures, and [`ShapeGroup`](/docs/core#shapegroup) outputs, translating each node by a computed offset while preserving names, colors, and nesting. Returns the same structure type as the input. In `radial` mode the algorithm is branch-aware and parent-relative: each node fans out from its immediate parent's center, so nested assemblies peel apart level by level. Named items may also include an inline `explode: { stage?, direction?, axisLock? }` property to override per-item behavior. Use this function when you want to bake the explode offset into the geometry before returning (e.g. to drive the amount with a `param()` slider). For a viewport-only explode slider without rerunning the script, use [`explodeView()`](/docs/viewport#explodeview) instead. **Example** ```js const explodeAmt = param('Explode', 0, { min: 0, max: 40, unit: 'mm' }); return lib.explode(assembly, { amount: explodeAmt, stages: [0.4, 0.8], mode: 'radial', byName: { Shaft: { direction: [1, 0, 0], stage: 1.4 } }, }); ```
- `hexNut(acrossFlats: number, height: number, holeDia: number): Shape` — Generic hex nut with a cylindrical bore. Constructed via intersection of three rotated rectangular slabs, then a bore is subtracted. Centered at origin, height along Z. For standard ISO metric nuts by thread size, use `lib.nut` instead.
- `bracket(width: number, height: number, depth: number, thick: number, holeDia?: number): Shape` — L-shaped mounting bracket with optional through-holes. Produces a right-angle bracket: a horizontal base plate and a vertical wall. Both legs share `width`. Optional holes are drilled through the base (along Z) and the wall (along Y).
- `holePattern(rows: number, cols: number, spacingX: number, spacingY: number, holeDia: number, depth: number): Shape` — Rectangular grid of cylindrical hole cutters. Returns the union of `rows × cols` cylinders laid out on a regular grid. Subtract from a solid to produce the full pattern. **Example** ```ts const pattern = lib.holePattern(3, 4, 20, 20, 4, 10); const panel = box(80, 70, 10).subtract(pattern.translate(-30, -20, 0)); ```
- `thread(diameter: number, pitch: number, length: number, options?: { depth?: number; segments?: number; }): Shape` — External helical thread — clean mesh, no SDF grid artifacts. **Details** Builds a cross-section with a single trapezoidal tooth from the root radius out to the crest radius, then twist-extrudes it so the tooth traces a helix. Manifold's extrude+twist produces structured quad-based geometry that follows the thread profile cleanly. Returns a threaded cylinder along +Z from z=0 to z=length. **Example** ```ts const t = lib.thread(5, 0.8, 12); // M5 × 0.8 pitch, 12 mm long ```
- `bolt(diameter: number, length: number, options?: { ... }): Shape` — ISO-style hex bolt with real helical threads. **Details** The hex head sits from z=0 up to z=headHeight. The shaft extends downward along −Z by `length` mm. An unthreaded shank section is included when `threadLength < length`. Default proportions follow ISO 4762 loosely: pitch ≈ 0.15×diameter, head height ≈ 0.65×diameter, across-flats ≈ 1.6×diameter. For standard M-size bolts pre-configured for a complete joint, use { **Example** ```ts const b = lib.bolt(5, 20); // M5 × 20 mm ```
- `nut(diameter: number, options?: { pitch?: number; height?: number; acrossFlats?: number; segments?: number; }): Shape` — ISO-style hex nut with a threaded bore. **Details** Constructed from the intersection of three rotated slabs with a cylindrical bore subtracted. The nut is centered at the origin, height along Z. Default proportions follow ISO 4032 loosely: height ≈ 0.8×diameter, across-flats ≈ 1.6×diameter. The bore is a clearance bore (not modelled with helical threads) for rendering efficiency. For standard M-size nuts pre-configured for a complete joint, use { **Example** ```ts const n = lib.nut(5); // M5 nut ```
- `washer(size: MetricSize, options?: { standard?: WasherStandard; segments?: number; }): Shape` — ISO metric flat washer (DIN 125-A). **Details** Returns a flat ring centered at the origin, thickness along Z. Dimensions are taken from { **Example** ```ts const w = lib.washer('M5'); // DIN 125-A M5 washer ```
- `fastenerSet(size: MetricSize, boltLength: number, options?: FastenerSetOptions): FastenerSetResult` — Complete ISO metric fastener set — bolt, nut, optional washers, and matching hole cutters. **Details** Returns all geometry for one bolted joint: the bolt, nut, up to two washers, a clearance-hole cutter, and a tap-drill cutter. All shapes are returned **un-positioned** (each on the Z-axis). Place them with `.translate()`. Sizes outside M4–M10 are supported for the washer (M2–M10); unsupported combinations will throw. **Example** ```ts const hw = lib.fastenerSet('M5', 20); const topPlate = box(60, 40, 8).translate(0, 0, 12) .subtract(hw.clearanceHole.translate(15, 10, 12)); const botPlate = box(60, 40, 8) .subtract(hw.clearanceHole.translate(15, 10, 0)); return [ { name: 'Top Plate', shape: topPlate }, { name: 'Bot Plate', shape: botPlate }, { name: 'Bolt', shape: hw.bolt.translate(15, 10, 20) }, { name: 'Nut', shape: hw.nut.translate(15, 10, -4) }, ]; ```
- `boltedServiceCover(options: BoltedServiceCoverOptions): BoltedServiceCoverResult` — Bolted service-cover interface with real seats, aligned holes, gasket, fused pull tabs, and installed screws. **Details** This is a higher-level mechanical pattern for the common "removable service cover" failure mode. It creates the parent ledge, cover, gasket, and screws from one shared bolt pattern so agents do not place decorative screw heads or floating pull tabs by eye. Coordinate convention: the parent frame sits from `z=0` to `parentThickness`, the gasket sits on the ledge, the cover sits above the gasket, and screw shafts run downward through the cover into the parent. All parts are centered on the XY origin. **Example** ```ts const cover = lib.boltedServiceCover({ width: 90, depth: 56, screwSize: 'M4', ledgeWidth: 10, boltInset: [6, 6], }); verify.equal('four retained cover screws', cover.screws.length, 4); return cover.parts; ```
- `datumEnclosureAssembly(options: DatumEnclosureAssemblyOptions): DatumEnclosureAssemblyResult` — Datum-driven enclosure tray with shared wall, ledge, standoff, cover, gasket, port, and screw geometry. **Details** This pattern is for electronics boxes, thermostat backplates, service-stack housings, camera housings, and small fixtures where generated models often place panels, ribs, bosses, ports, and covers by eye. The tray, internal ledges, standoffs, ribs, service port, gasket, cover holes, and installed screws all come from one datum system. This keeps screw axes, boss locations, wall thickness, and service openings aligned instead of relying on independent magic numbers. Coordinate convention: X/Y are the enclosure footprint, Z is up. The base tray starts at `z=0` and rises to `height`; the gasket and cover sit above the top ledge with small explicit face clearances. **Example** ```ts const enclosure = lib.datumEnclosureAssembly({ width: 96, depth: 64, height: 18, }); verify.notColliding('cover clears enclosure gasket', enclosure.cover, enclosure.gasket); verify.inRange('cover stack has small seating clearance', enclosure.dims.faceClearance, 0.01, 0.08); return enclosure.parts; ```
- `snapLatchCoverAssembly(options: SnapLatchCoverAssemblyOptions): SnapLatchCoverAssemblyResult` — Snap-retained cover with a receiver frame, latch windows, underside catch lands, and fused snap hooks. **Details** This pattern is for covers, cartridges, clasps, and small housings where agents often add decorative tabs without a catch. The receiver has a real service opening plus two clearance latch windows. The cover is one fused part with two flexible-looking snap fingers that pass through the windows and barb under the receiver underside. Nothing intersects in the final assembly; the hook geometry sits close enough to the catch lands to prove retention intent. Coordinate convention: the receiver frame sits from `z=0` to `parentThickness`; the cover is seated just above the receiver on +Z. Two snap hooks sit on the +/-Y ledges and tuck under the receiver. **Example** ```ts const snapCover = lib.snapLatchCoverAssembly({ width: 72, depth: 44, }); verify.notColliding('snap hooks clear receiver windows', snapCover.cover, snapCover.parent); verify.inRange('snap cover has small seating clearance', snapCover.dims.faceClearance, 0.01, 0.08); return snapCover.parts; ```
- `pinnedLeverAssembly(options: PinnedLeverAssemblyOptions): PinnedLeverAssemblyResult` — Retained pinned lever stack with a fused hub/arm/grip, low stop land, pivot pin, bore cutters, and thrust washers. **Details** This pattern is for the common handle/lever failure mode where a visual arm, hub, washer, and pin are placed near each other but never form a credible mechanism. The lever body is one fused part, the pin runs through aligned bores, washers sit on both sides of the lever, and the support includes a bearing land plus an optional low stop land beside the lever path. Coordinate convention: pivot axis is +Z at the XY origin. The support starts at `z=0`, the lower washer sits on top of the support, the lever sits on the lower washer, the upper washer sits on the lever, and the retained pin spans the full stack. **Example** ```ts const lever = lib.pinnedLeverAssembly({ armLength: 54, armWidth: 10, pinDiameter: 5, }); verify.equal('lever stack has five retained parts', lever.parts.length, 5); return lever.parts; ```
- `retainedShaftAssembly(options: RetainedShaftAssemblyOptions): RetainedShaftAssemblyResult` — Retained shaft, washer, knob, and support-cheek stack for trunnions, pivots, and adjustable clamps. **Details** This pattern replaces the common "pin, washers, and knob are near each other" visual shortcut with a mechanically accountable shaft stack. The two support cheeks get matching clearance bores, the through shaft spans the whole stack, washers and knobs share the same axis, and retaining heads keep the knobs from reading as loose floating cylinders. Coordinate convention: the shaft axis is +X through the world origin. Support cheeks are centered at `x = +/- supportSpacing / 2`. The supports are bored for clearance, so collision inspection should report no support/shaft overlap while the connectivity audit still sees one retained stack. **Example** ```ts const trunnion = lib.retainedShaftAssembly({ supportSpacing: 96, shaftDiameter: 8, supportHeight: 42, }); verify.equal('retained shaft stack has seven parts', trunnion.parts.length, 7); return trunnion.parts; ```
- `capturedLinearSlide(options: CapturedLinearSlideOptions): CapturedLinearSlideResult` — Captured linear slide with a U-channel rail, return lips, end stops, and a carriage posed inside the guide. **Details** This pattern is for drawer-slide, quick-release plate, and guided-carriage models where agents often place rail details and a moving block near each other without a capture relationship. The rail is one fused part with side walls, inward lips, and end stops; the carriage is wider than the lip throat but narrower than the inner rail width, so it is mechanically captured while retaining explicit clearance. Coordinate convention: rail length is along X, width is along Y, and Z is up. The rail base starts at `z=0`; the carriage sits above the base and below the return lips. `travel=0` places the carriage at the negative-X end of travel, and `travel=maxTravel` places it at the positive-X end. **Example** ```ts const slide = lib.capturedLinearSlide({ length: 160, carriageLength: 52, travel: 42, }); verify.greaterThan('carriage is captured by return lips', slide.dims.carriageWidth, slide.dims.throatWidth); return slide.parts; ```
- `capturedCartridgeGuideAssembly(options: CapturedCartridgeGuideAssemblyOptions): CapturedCartridgeGuideAssemblyResult` — Captured removable cartridge guide with return lips, rear stop, wide cartridge flange, and pull tab. **Details** This pattern is for pump cartridges, filter cassettes, skeg cassettes, battery cartridges, and slide-in service modules where generated models often place a tray and a loose block near each other. The guide is one fused part with side walls, inward return lips, and a rear stop. The cartridge has a wide lower flange captured under the lips and a narrower body that passes through the throat, so the model has a real retention contract without manual coordinate tuning. Coordinate convention: insertion travel is along +X. The open entry is at −X, the rear stop is at +X, the guide base starts at `z=0`, and `insertion=0` places the cartridge at the front travel limit. **Example** ```ts const cassette = lib.capturedCartridgeGuideAssembly({ length: 150, cartridgeLength: 72, }); verify.notColliding('cartridge clears guide rails', cassette.cartridge, cassette.guide); verify.greaterThan('cartridge flange is captured by lips', cassette.dims.cartridgeWidth, cassette.dims.throatWidth); return cassette.parts; ```
- `livingHingeCoverAssembly(options: LivingHingeCoverAssemblyOptions): LivingHingeCoverAssemblyResult` — One-piece molded living-hinge cover strip with a fixed leaf, thin flexible web, cover leaf, pull lip, snap barb, and catch land. **Details** This pattern is for small polypropylene-style lids, battery doors, sample covers, blister latches, and molded service flaps where generated models often draw a decorative hinge strip between two disconnected plates. It returns one fused molded part in its as-molded flat state: fixed mounting leaf, thin hinge web, moving cover leaf, pull lip, raised snap barb, and catch land. The flexible web is intentionally much thinner than the rigid leaves and shares material with both leaves. Coordinate convention: X is hinge length/part width, Y runs from fixed leaf through hinge web to cover leaf, and Z is thickness. The hinge web is centered on `y=0`; the fixed leaf lies at −Y and the cover leaf at +Y. **Example** ```ts const livingCover = lib.livingHingeCoverAssembly({ width: 64, coverDepth: 42, }); verify.greaterThan('living hinge is much thinner than rigid leaves', livingCover.dims.flexRatio, 3); return livingCover.parts; ```
- `knuckledHingeAssembly(options: KnuckledHingeAssemblyOptions): KnuckledHingeAssemblyResult` — Alternating knuckle hinge with two fused leaves and a retained pin. **Details** This pattern replaces hand-placed hinge barrels and pin ghosts with a mechanically accountable hinge. The fixed leaf owns every other knuckle, the moving leaf owns the alternating knuckles, all knuckles share one bore size, and the retained pin spans the full stack with heads outside the barrels. Coordinate convention: the hinge pin axis is +X through the world origin. The fixed leaf extends toward +Y. The moving leaf extends toward -Y and rotates about +X by `openAngleDeg`. **Example** ```ts const hinge = lib.knuckledHingeAssembly({ length: 70, leafLength: 28, openAngleDeg: 45, }); verify.equal('hinge has two leaves and one retained pin', hinge.parts.length, 3); return hinge.parts; ```
- `clevisPinJointAssembly(options?: ClevisPinJointAssemblyOptions): ClevisPinJointAssemblyResult` — Clevis-style pin joint with bored yoke ears, a center link eye, and a retained pin. **Details** This pattern is for crank links, damper rod ends, pump crossheads, capo/cam pivots, and small mechanism joints where agents often place an eyelet and a pin near a bracket without modeling the captured load path. The clevis is one fused part with two bored ears and a rear bridge, the center link has a real eye and arm, and the retained pin spans the full stack with heads outside the ears. Coordinate convention: the pin axis is +Y through the world origin. The center link arm extends toward +X. The clevis bridge sits behind the eye on -X, leaving the link eye clear inside the yoke. **Example** ```ts const clevis = lib.clevisPinJointAssembly({ pinDiameter: 4, linkArmLength: 38, }); verify.equal('clevis joint has three retained parts', clevis.parts.length, 3); return clevis.parts; ```
- `seatedBearingAssembly(options: SeatedBearingAssemblyOptions): SeatedBearingAssemblyResult` — Seated radial-bearing support with a real counterbore, shoulder, through shaft, and retaining collars. **Details** This pattern is for purchased bearings, rollers, burr-cartridge shafts, and small spindle supports where agents often place a ring and a shaft near a block without modelling the pocket that locates the bearing. The housing includes a through-bore and a larger counterbore that leaves a shoulder for the bearing outer race. The shaft is smaller than the bearing bore and carries collars outside the housing, so collision checks can distinguish intended clearance from impossible overlap. Coordinate convention: the shaft axis is +Z through the world origin. The housing block starts at `z=0`, the raised boss is on top of the block, the bearing is seated from the top counterbore, and the shaft extends above and below the housing. **Example** ```ts const bearingStack = lib.seatedBearingAssembly({ bearingOuterDiameter: 22, bearingInnerDiameter: 8, bearingWidth: 7, }); verify.greaterThan('housing has wall around bearing pocket', bearingStack.dims.bossOuterDiameter - bearingStack.dims.pocketDiameter, 4); return bearingStack.parts; ```
- `cableGlandAnchorAssembly(options: CableGlandAnchorAssemblyOptions): CableGlandAnchorAssemblyResult` — Cable, wire, or tube gland anchor with a real panel hole, hollow gland body, compression nut, and routed cable. **Details** This pattern is for pumps, filters, electronics boxes, vents, monitors, and fixtures where generated models often leave hoses or cables terminating in space. It creates the receiving panel hole, a hollow gland body with a panel-side flange seated in a shallow pocket, a hollow compression nut, and a cable/tube that runs through the gland bore with explicit clearance. Coordinate convention: the cable axis is +X through the world origin. The panel is centered around `x=0` with thickness along X; the flange sits on the +X side of the panel and the compression nut sits on the −X side. The cable spans the full anchor. **Example** ```ts const anchor = lib.cableGlandAnchorAssembly({ cableDiameter: 6, panelThickness: 3, }); verify.notColliding('cable clears gland bore', anchor.cable, anchor.gland); verify.clearanceBetween('gland flange is seated at panel pocket', anchor.gland, anchor.panel, 0.01, 0.2); return anchor.parts; ```
- `hoseBarbPortAssembly(options: HoseBarbPortAssemblyOptions): HoseBarbPortAssemblyResult` — Hose-barb pump/filter port with a bored receiver, shoulder, barb ridges, installed hose, and clamp band. **Details** This pattern is for pump heads, filters, vents, lab cartridges, and fluid fittings where generated models often leave tubes ending near a block. The receiver has a real through-port and raised boss, the fitting is hollow with a shoulder and multiple barb ridges, and the hose is modeled as an installed tube over the barb envelope with a clamp band. The hose bore is sized for the deformed installed hose, so collision checks distinguish the retained interface from impossible solid overlap. Coordinate convention: the fluid axis is +X through the world origin. The receiver block is centered around `x=0`; the raised boss and hose are on the +X side. **Example** ```ts const hosePort = lib.hoseBarbPortAssembly({ hoseInnerDiameter: 6, hoseOuterDiameter: 10, }); verify.notColliding('hose clears barb peaks', hosePort.hose, hosePort.fitting); verify.inRange('fitting shoulder seats near boss face', hosePort.dims.faceClearance, 0.01, 0.08); return hosePort.parts; ```
- `routedTubeClipAssembly(options: RoutedTubeClipAssemblyOptions): RoutedTubeClipAssemblyResult` — Routed tube or cable retained by saddle clips with real bores, screw holes, and installed screws. **Details** This pattern is for hoses, wires, pump tubes, sensor leads, and appliance cable runs where generated models often draw a cylinder near a wall without clips or strain relief. The base panel has receiving screw envelopes, each saddle clip has a real through-bore around the tube and vertical screw clearances, and the installed screws share those positions. Coordinate convention: the routed tube runs along +X through the world origin. The base panel starts at `z=0`; clips sit on top of the panel, and the tube passes through their bores. **Example** ```ts const route = lib.routedTubeClipAssembly({ tubeDiameter: 6, clipCount: 3, }); verify.notColliding('tube clears clip bores', route.tube, union(...route.clips)); verify.notColliding('clip screws clear retained stack', union(...route.screws), union(route.panel, ...route.clips)); return route.parts; ```
- `pcbTerminalBlockAssembly(options?: PcbTerminalBlockAssemblyOptions): PcbTerminalBlockAssemblyResult` — PCB terminal-block stack with a backplate, standoffs, mounting screws, pin holes, and a seated terminal block. **Details** This pattern is for thermostat backplates, appliance control panels, sensor boards, and small electronics where generated models often place a terminal block, screw heads, and holes as independent decorations. The PCB mounting holes, fused standoffs, installed screws, terminal pins, and PCB pin clearances all come from one shared datum system so the purchased block is mechanically seated and the board is actually mounted. Coordinate convention: X/Y are the board footprint, Z is up. The backplate starts at `z=0`, standoffs rise from the plate, the PCB rests on the standoffs, and the terminal block sits on top of the PCB near the front edge. **Example** ```ts const terminalStack = lib.pcbTerminalBlockAssembly({ terminalCount: 5, screwSize: 'M3', }); verify.notColliding('terminal pins clear PCB holes', terminalStack.terminalBlock, terminalStack.pcb); verify.notColliding('mounting screws clear PCB and standoff holes', union(...terminalStack.screws), union(terminalStack.pcb, terminalStack.backplate)); return terminalStack.parts; ```
- `thumbScrewClampAssembly(options?: ThumbScrewClampAssemblyOptions): ThumbScrewClampAssemblyResult` — Thumb-screw clamp with a C-frame, threaded boss, captive pressure pad, knob, and clamped workpiece. **Details** This pattern is for bench clamps, monitor-arm desk clamps, small vise screws, capo pressure screws, fixture hold-downs, and service brackets where generated models often place a loose screw, knob, or pressure pad near a bracket. The helper creates a one-piece clamp frame with a fixed anvil pad, a bored threaded support and boss, an installed screw with a captive pressure pad and hand knob, and a representative clamped workpiece seated between the pads. Coordinate convention: the clamp screw runs along +X. The fixed anvil is on the -X side, the threaded support and knob are on the +X side, and Z is up from the base bridge. **Example** ```ts const clamp = lib.thumbScrewClampAssembly({ screwSize: 'M6', workpieceThickness: 20, }); verify.notColliding('thumb screw clears threaded boss', clamp.clampScrew, clamp.frame); verify.clearanceBetween('pressure pad is seated on workpiece', clamp.clampScrew, clamp.workpiece, -0.01, 0.05); return clamp.parts; ```
- `pipeRoute(points: [ number, number, number ][], radius: number, options?: { bendRadius?: number; wall?: number; segments?: number; }): Shape` — Route a pipe (solid or hollow) through 3D waypoints with smooth bends. Each interior waypoint gets a torus-section bend. Straight segments connect them. Returns a single unioned Shape.
- `elbow(pipeRadius: number, bendRadius: number, angle?: number | { ... }, options?: { ... }): Shape` — Pipe elbow — a curved pipe section (torus arc) for connecting two pipe directions. By default creates a bend in the XZ plane: incoming along +Z, outgoing rotated by `angle`. The bend starts at the origin, curving away from it.
- `beltDrive(options: BeltDriveOptions): BeltDriveResult` — Create a flat open-belt body around two pulley pitch circles. The belt is generated as a tangent loop in the XY plane and extruded along +Z by `beltWidth`. The result includes the solid belt, the 2D belt profile, a thin pitch-path sketch for visualization, total belt length, tangent spans, and wrap metadata for each pulley. For more than two pulleys, the API intentionally asks for route intent before geometry is created. Use `route: "outer"` for the future outside-envelope mode, or an ordered route for future serpentine/idler layouts. ```ts const drive = lib.beltDrive({ pulleys: [ { name: "motor", center: [0, 0], pitchRadius: 12 }, { name: "output", center: [80, 0], pitchRadius: 28 }, ], beltWidth: 8, beltThickness: 2, }); return drive.belt; ```
- `tangentLoop2d(circles: TangentCircle2D[], options?: TangentLoop2DOptions): TangentLoop2D` — Build a closed 2D route made from common tangent spans and pulley wrap arcs. Use this when you need reusable belt/chain route geometry before creating a solid body. The first implementation supports two circles. `mode: "open"` uses external tangents; `mode: "crossed"` uses internal tangents. ```ts const route = lib.tangentLoop2d([ { center: [0, 0], radius: 12 }, { center: [80, 0], radius: 28 }, ]); const belt = route.offsetBand(2).extrude(8); ```
- `tSlotProfile(options?: TSlotProfileOptions): Sketch` — Build a 2D T-slot cross-section sketch. Default parameters describe a 20x20 B-type profile with slot 6. Use this when you want a drawing-ready profile sketch before extrusion.
- `tSlotExtrusion(length: number, options?: TSlotExtrusionOptions): Shape` — Build a T-slot extrusion from the generated 2D profile. Extrudes along +Z by default.
- `profile2020BSlot6Profile(options?: Profile2020BSlot6ProfileOptions): Sketch` — Accurate-ish 2D profile for 20x20 B-type slot 6. Returns a drawing-ready Sketch centered at origin.
- `profile2020BSlot6(length: number, options?: Profile2020BSlot6Options): Shape` — 20x20 B-type slot 6 extrusion with profile-accurate defaults. Pass option overrides if your supplier's profile differs slightly.
- `spurGear(options: SpurGearOptions): Shape` — Involute external spur gear with optional center bore. Specify module, teeth, faceWidth as required parameters. Optional tuning includes pressureAngleDeg (default 20), backlash, clearance, addendum, dedendum, boreDiameter, and segmentsPerTooth (default 10). **Connectors (for assembly-based positioning):** - `bore`: revolute connector at the bore center, axis along +Z. Carries measurements: `{ module, teeth, pitchRadius, outerRadius, faceWidth }`. Use `.connect("Housing.seat", "Gear.bore")` to mount a gear on a shaft seat.
- `bevelGear(options: BevelGearOptions): Shape` — Conical bevel gear generated from a tapered involute extrusion. Specify pitchAngleDeg directly or derive it from mateTeeth + shaftAngleDeg. **Connectors (for assembly-based positioning):** - `bore`: revolute connector at the large-end bore center (Z=0), axis along -Z (away from teeth). - `apex`: connector at the cone apex above the gear (the point where the pitch cone converges), axis along +Z. Useful for meshing two bevel gears — their apices should coincide. Carries measurements: `{ module, teeth, pitchRadius, pitchAngleDeg, coneDistance, faceWidth }`.
- `faceGear(options: FaceGearOptions): Shape` — Face gear (crown style) where teeth are on one face (top or bottom) instead of the outer rim. Uses the same involute tooth sizing as spurGear, then projects the tooth band axially from one side. Alias for sideGear (which is kept for backward compatibility).
- `sideGear(options: SideGearOptions): Shape` — Crown/face style gear where the teeth project from one side of the disk instead of the outer cylindrical rim.
- `ringGear(options: RingGearOptions): Shape` — Internal ring gear with involute-derived tooth spaces. Specify rimWidth or outerDiameter for the annular body. **Connectors (for assembly-based positioning):** - `bore`: connector at the ring center, axis along +Z. For planetary gearboxes, this is where the ring mounts to the housing. Carries measurements: `{ module, teeth, pitchRadius, innerRadius, outerRadius, faceWidth }`.
- `rackGear(options: RackGearOptions): Shape` — Linear rack gear with pressure-angle flanks. Use with spurGear for rack-and-pinion mechanisms. **Orientation:** teeth run along the X axis with tooth tips pointing +Y (pitch line at Y=0). The rack is extruded +Z by `faceWidth`. Rotate the rack to align with a different slide axis. **Connectors (for assembly-based positioning):** - `teeth`: prismatic connector at the pitch line center, axis along +X (slide direction). Carries measurements: `{ module, teeth, faceWidth, length }`. Connect to a housing's rack channel: ```js housing.withConnectors({ rack_channel: connector("rack-channel", { origin: [pitchR, 0, channelZ], axis: [1, 0, 0], kind: "prismatic", }), }); assembly.connect("Housing.rack_channel", "Rack.teeth", { as: "slide" }); ```
- `gearPair(options: GearPairOptions): GearPairResult` — Build or validate a spur-gear pair and return ratio, backlash, and mesh diagnostics. Accepts either shapes from spurGear() or analytical specs for each member. When place is true (default), the gear is auto-positioned at the correct center distance.
- `bevelGearPair(options: BevelGearPairOptions): BevelGearPairResult` — Build or validate a bevel-gear pair and return ratio diagnostics plus recommended joint placement vectors.
- `faceGearPair(options: FaceGearPairOptions): FaceGearPairResult` — Build or validate a perpendicular pair between a face gear and a vertical spur gear.
- `sideGearPair(options: SideGearPairOptions): SideGearPairResult` — Pair helper for side (crown/face) gear + perpendicular "vertical" spur gear. Auto-placement rotates the spur around +Y and positions it to mesh at the side tooth band.
- `gearRatio(teethA: number, teethB: number, options?: { internal?: boolean; }): number` — Coupling ratio between two meshed spur gears. When gear A turns 1°, gear B turns `-teethA / teethB` degrees (negative because meshed external gears rotate in opposite directions). Pass `{ internal: true }` for internal gear pairs (ring gear + spur/planet), where the two rotate in the same direction.
- `rackRatio(module: number, pinionTeeth: number): number` — Coupling ratio between a pinion and a rack. When the pinion rotates by `θ` degrees, the rack slides by `θ × (π × module × teeth / 360)` mm. Equivalently, 1mm of rack travel = `180 / (π × pitchRadius)` degrees of pinion rotation.
- `planetaryRatio(sunTeeth: number, ringTeeth: number): number` — Planetary gear reduction ratio when the ring is held fixed. Input: sun. Output: carrier. Ratio: `1 + ringTeeth / sunTeeth`. One turn of the sun produces `1 / ratio` turns of the carrier.
- `boltPattern(options: BoltPatternOptions): BoltPattern` — Define a bolt pattern once and cut it from multiple parts. const base = bolts.cut(box(60, 50, 10), 12, { from: -1 }); const cover = bolts.cut(box(60, 50, 3), 5, { from: -1 }); // Same positions in both parts — guaranteed aligned. ```
- `driveWheel(options?: DriveWheelOptions): DriveWheelBuilder` — Start a composable exceptional gear or drive wheel.
- `readDriveWheelMeta(shape: Shape): DriveWheelMeta | null` — Read the functional-region metadata attached by `driveWheel().build()`.
- `sectorGear(options: SectorGearOptions): Shape` — Involute sector gear with teeth on only part of the pitch circle. Specify the full-circle pitch as `teethOnFullCircle`, then choose the active tooth window with `firstTooth` and `toothCount`. The body is separate from the tooth region: pass a `gearBody...` shape for spokes, hubs, and product styling, or omit it for a simple root-radius disk. **Example** ```ts const body = lib.gearBodies.spoked({ outerRadius: 22, rimWidth: 3, hubDiameter: 10, spokeCount: 5, spokeWidth: 2.5, faceWidth: 8, boreDiameter: 5, }); const sector = lib.sectorGear({ module: 1.25, teethOnFullCircle: 36, toothCount: 10, faceWidth: 8, body, }); ```
- `gearBodies: { ... }` — Gear body preset namespace: disk, diskWithHub, spoked, and fromProfile.
- `gearBodyDisk(options: GearBodyDiskOptions): Shape` — Solid disk/ring gear body, independent from any tooth geometry.
- `gearBodyDiskWithHub(options: GearBodyDiskWithHubOptions): Shape` — Disk gear body with a raised center hub.
- `gearBodySpoked(options: GearBodySpokedOptions): Shape` — Spoked gear body with an outer rim, center hub, and radial spokes.
- `gearBodyFromProfile(profile: Sketch, options: GearBodyFromProfileOptions): Shape` — Extrude a custom 2D profile into a gear body.

---

<!-- generated/wood.md -->

# Woodworking

Wood boards with grain/species metadata, and joinery operations: dado, rabbet, mortise & tenon. Access via `Wood.*`.

## Contents

- [WoodBoard](#woodboard)
- [Wood](#wood)

---

## Classes

### `WoodBoard`

A board of wood with metadata for manufacturing: grain direction, species, and dimensions. The underlying geometry is a simple box.

WoodBoard operations are immutable. Joint operations return new boards instead of carving the original in-place, and transform methods preserve all metadata.

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `shape` | `Shape` | The underlying 3D shape. |
| `width` | `number` | Board width (mm) — the longer flat dimension |
| `height` | `number` | Board height (mm) — the shorter flat dimension |
| `thickness` | `number` | Board thickness (mm) |
| `grain` | `string` | Grain direction: "long" or "cross" |
| `species` | `string` | Wood species, e.g. "birch", "oak" |
| `material` | `string` | Material label for BOM |

**Methods:**

#### `cut()` — Subtract a cutter from this board, returning a new board. Used by joint functions (dado, rabbet, mortiseAndTenon).

```ts
cut(cutter: Shape): WoodBoard
```

#### `translate()` — Translate the board in 3D space.

```ts
translate(x: number, y: number, z: number): WoodBoard
```

#### `rotate()` — Rotate the board around an axis by a given angle in degrees.

```ts
rotate(axis: [ number, number, number ], angleDeg: number, options?: { pivot?: [ number, number, number ]; }): WoodBoard
```

#### `rotateX()` — Rotate the board around the X axis by a given angle in degrees.

```ts
rotateX(angleDeg: number): WoodBoard
```

#### `rotateY()` — Rotate the board around the Y axis by a given angle in degrees.

```ts
rotateY(angleDeg: number): WoodBoard
```

#### `rotateZ()` — Rotate the board around the Z axis by a given angle in degrees.

```ts
rotateZ(angleDeg: number): WoodBoard
```

#### `mirror()` — Mirror the board across a plane defined by its normal.

```ts
mirror(normal: [ number, number, number ]): WoodBoard
```

#### `color()` — Set the board's display color.

```ts
color(value: string): WoodBoard
```

#### `clone()` — Clone the board (creates an independent copy of the underlying shape).

```ts
clone(): WoodBoard
```

---

## Constants

### `Wood`

Woodworking namespace — create boards and cut joints.

**Boards:** `Wood.board()` creates a WoodBoard with grain, species, and BOM metadata.

**Joints:** `Wood.dado()`, `Wood.rabbet()`, and `Wood.mortiseAndTenon()` are immutable — they return new board value(s) with the joint cut applied.

- `readonly board: (width: number, height: number, thickness: number, opts?: WoodBoardOptions) => WoodBoard` — Create a wood board with metadata for manufacturing. The board is a box(width, height, thickness) centered on XY, base at Z=0. Width along X, height along Y, thickness along Z (0 to thickness).
- `dado(host: WoodBoard, guest: WoodBoard, opts: DadoOptions): WoodBoard` — Cut a dado (channel) across the face of a host board for a guest board to sit in. Returns a new host board with the dado cut applied.
- `rabbet(board: WoodBoard, opts: RabbetOptions): WoodBoard` — Cut a rabbet (L-shaped step) along an edge of a board. Returns a new board with the rabbet cut applied.
- `mortiseAndTenon(mortiseBoard: WoodBoard, tenonBoard: WoodBoard, opts?: MortiseAndTenonOptions): MortiseAndTenonResult` — Cut a mortise in one board and shape a tenon on another. Returns new boards with the mortise pocket and tenon cuts applied.

---

<!-- generated/viewport.md -->

# Viewport & Runtime

Cut planes, exploded views, joint animations, and scene configuration.

## Contents

- [Viewport & Runtime](#viewport-runtime) — `Viewport.label`, `scene`, `viewConfig`, `explodeView`, `jointsView`, `compareWith`, `cutPlane`, `mock`, `showLabels`, `highlight`
- [RouteBuilder](#routebuilder)
- [route](#route)

## Functions

### Viewport & Runtime

#### `Viewport.label()` — Add a render-only viewport label at a world-space point.

`Viewport.label()` is for temporary review, debug, tutorial, or explicitly requested presentation overlays. It does not create sketches, meshes, B-rep topology, exported text, or face labels, so it stays off the OCCT path. Default production models should be understandable from physical geometry, materials, part boundaries, and named objects, not viewport annotations.

Use [`text2d()`](/docs/sketch#text2d) only when the letters should become manufactured geometry, such as raised lettering, engraved serial numbers, or exported nameplates.

Labels are collected during script execution and rendered by the viewport as lightweight overlay annotations. They are ignored by exports and do not appear in `objects`.

```js
Viewport.label('Bearing bore', [0, 0, 18], {
  color: '#f8fafc',
  background: '#0f172acc',
  offset: [0, 0, 8],
  anchor: 'bottom',
});

return box(40, 30, 12);
```

```ts
Viewport.label(text: string, at: [ number, number, number ], options?: RenderLabelOptions): void
```

**`RenderLabelOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `color?` | `string` | Text color as any CSS color string. |
| `background?` | `string` | Background color as any CSS color string. Use `'transparent'` for no pill background. |
| `size?` | `number` | Font size in CSS pixels. Defaults to 12. |
| `offset?` | `[ number, number, number ]` | Additional world-space offset from `at`. |
| `anchor?` | `RenderLabelAnchor` | Which point of the label box is anchored to `at`. Defaults to `'center'`. |
| `alwaysOnTop?` | `boolean` | When false, the label is hidden when occluded by scene geometry. Defaults to true. |

#### `scene()` — Configure the scene environment for the current script execution.

Controls camera position, named render views, optional model journeys, lighting rig, background color or gradient, atmospheric fog, environment maps, post-processing effects, and capture parameters for the `forgecad capture` command. Multiple calls merge — later values override earlier ones on a per-key basis, so you can split configuration across multiple `scene()` calls.

When `lights` is specified, **all** default lights are removed. You must include your own ambient light or the scene will be fully dark.

Setting `camera.position` overrides auto-framing — the viewport will no longer auto-fit the geometry on script reload.

Named render views let scripts check in repeatable cameras next to the model code. The canonical shape is `{ camera: { position, target } }`, and a direct camera shorthand `{ position, target }` is also accepted. Use the canonical shape when you may add view metadata later. Use it from the CLI with `--view hero` on `forgecad render 3d`, `forgecad render hq`, or `forgecad capture`.

Model journeys let scripts check in a compact guided path through named objects. Each journey has ordered `steps`; each step can name a `focus` target by object name/tree path, provide a caption, and optionally provide an explicit camera. In the viewer, journeys are opt-in: they appear as a small Explore control and do not move the camera until the user starts them. Use `forgecad run model.forge.js --journeys` or `--journeys-json` to inspect resolved targets.

Post-processing effects (`bloom`, `vignette`, `grain`) work in the browser viewport only. The CLI applies camera, lights, background, fog, and `toneMappingExposure` but skips shader effects.

All numeric values accept `param()` expressions.

```js
scene({
  background: { top: '#000814', bottom: '#001d3d' },
  camera: { position: [160, -120, 100], target: [0, 0, 50], fov: 52 },
  views: {
    hero: {
      camera: { position: [180, -140, 90], target: [0, 0, 25], up: [0, 0, 1], fov: 38 },
    },
    side: { position: [240, 0, 70], target: [0, 0, 25], fov: 34 },
  },
  journeys: {
    grandTour: {
      title: 'Grand Tour',
      startsAt: 'overview',
      steps: [
        { id: 'overview', focus: 'Solar System', caption: 'Start with the whole model.' },
        { id: 'earth', focus: 'Earth', caption: 'Fit and inspect Earth.' },
      ],
    },
  },
  lights: [
    { type: 'ambient', color: '#001233', intensity: 0.08 },
    { type: 'point', position: [120, -80, 130], color: '#00f5d4', intensity: 4, distance: 400, decay: 1 },
    { type: 'point', position: [-100, 60, 20], color: '#f72585', intensity: 3, distance: 350 },
    { type: 'directional', position: [50, -30, 200], color: '#ffd60a', intensity: 1.2 },
    { type: 'hemisphere', skyColor: '#003566', groundColor: '#000814', intensity: 0.2 },
  ],
  fog: { color: '#000814', near: 100, far: 450 },
  postProcessing: {
    bloom: { intensity: param('bloom', 1.5, 0, 4), threshold: 0.5, radius: 0.7 },
    vignette: { darkness: 0.8, offset: 0.25 },
    grain: { intensity: 0.08 },
    toneMappingExposure: param('exposure', 1.5, 0.5, 4),
  },
});
```

```ts
scene(options: SceneOptions): void
```

**`SceneOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `capture?` | `SceneCaptureConfig` | Default capture parameters for `forgecad capture` — CLI flags override these. |
| `background?`, `camera?`, `views?`, `journeys?`, `lights?`, `environment?`, `fog?`, `postProcessing?`, `ground?` | | — |

`SceneBackgroundGradient`: `{ top: string, bottom: string }`

**`SceneCameraConfig`**: `position?: [ number, number, number ]`, `target?: [ number, number, number ]`, `up?: [ number, number, number ]`, `fov?: number`, `type?: "perspective" | "orthographic"`

**`SceneJourneyConfig`**

| Option | Type | Description |
|--------|------|-------------|
| `title?` | `string` | Viewer-facing journey title. Defaults to the journey id. |
| `startsAt?` | `string` | Optional starting step id. Defaults to the first step. |
| `behavior?` | `"opt-in" \| "auto"` | Whether the viewer should offer or auto-open the journey. First slice supports opt-in. |
| `steps` | `SceneJourneyStepConfig[]` | Ordered journey spine. Branches can be added later without changing this core contract. |
| `valid?` | `boolean` | True unless any journey or step diagnostic has level "error". |

**`SceneJourneyStepConfig`**

| Option | Type | Description |
|--------|------|-------------|
| `id` | `string` | Stable step id used by viewer links and Next/Back state. |
| `title?` | `string` | Viewer-facing title. Defaults to the step id. |
| `focus?` | `string` | Object name or slash-separated tree path to focus. |
| `caption?` | `string` | Short optional viewer caption. |
| `camera?` | `SceneViewCameraConfig` | Optional explicit camera for this step. When omitted, the viewer fits `focus`. |
| `resolvedFocusId?` | `string \| null` | Resolved object id after script execution, when `focus` matched exactly one object. |
| `resolvedFocusPath?` | `string \| null` | Resolved object tree path or name after script execution. |

**`SceneLightConfig`**

| Option | Type | Description |
|--------|------|-------------|
| `target?` | `[ number, number, number ]` | Target for directional/spot lights |
| `groundColor?` | `string` | Ground color for hemisphere lights |
| `skyColor?` | `string` | Sky color alias for hemisphere lights (same as color) |
| `angle?` | `number` | Spot light cone angle in radians |
| `penumbra?` | `number` | Spot light penumbra (0–1) |
| `decay?` | `number` | Point/spot light decay |
| `distance?` | `number` | Point/spot light distance (0 = infinite) |
| `castShadow?` | `boolean` | Whether this light casts shadows |
| `type`, `color?`, `intensity?`, `position?` | | — |

**`SceneEnvironmentConfig`**
- `preset?: "studio" | "sunset" | "dawn" | "warehouse" | "forest" | "apartment" | "lobby" | "city" | "park" | "night" | "none"` — Built-in preset name or 'none' to disable
- `intensity?: number` — Environment map intensity
- `background?: boolean` — Use environment map as scene background

**`SceneFogConfig`**
- `near?: number` — Linear fog near distance
- `far?: number` — Linear fog far distance
- `density?: number` — Exponential fog density (if set, uses FogExp2 instead of linear Fog)
- Also: `color?: string`

`ScenePostProcessingConfig`: `{ bloom?: SceneBloomConfig, vignette?: SceneVignetteConfig, grain?: SceneGrainConfig, toneMappingExposure?: number }`

`SceneBloomConfig`: `{ intensity?: number, threshold?: number, radius?: number }`

`SceneVignetteConfig`: `{ darkness?: number, offset?: number }`

`SceneGrainConfig`: `{ intensity?: number }`

**`SceneGroundConfig`**

| Option | Type | Description |
|--------|------|-------------|
| `visible?` | `boolean` | Show a ground plane |
| `color?` | `string` | Ground color |
| `offset?` | `number` | Offset below the model's bounding box minimum Z. Default 0 (flush with model bottom). |
| `receiveShadow?` | `boolean` | Receive shadows on the ground |

**`SceneCaptureConfig`**

| Option | Type | Description |
|--------|------|-------------|
| `framesPerTurn?` | `number` | Frames for one full orbit rotation (default: 72) |
| `holdFrames?` | `number` | Frozen frames before motion starts (default: 6) |
| `pitchDeg?` | `number` | Orbit pitch angle in degrees (default: auto from camera) |
| `fps?` | `number` | Output frame rate (default: 24) |
| `size?` | `number` | Output frame size in pixels (default: 960) |
| `background?` | `string` | Canvas background color for capture (default: '#252526') |

#### `viewConfig()` — Configure viewport helper visuals for the current script execution.

Controls renderer-only overlays that appear in the viewport but are not part of the geometry. Currently supports the joint overlay that renders axis arrows and arc indicators when `jointsView` is active. Multiple calls merge — later values override earlier ones per key.

This does **not** trigger a geometry recompute; it only affects the visual helpers drawn on top of the 3D scene.

```js
viewConfig({
  jointOverlay: {
    axisColor: '#13dfff',
    arcColor: '#ff7a1a',
    axisLineRadiusScale: 0.03,
    arcLineRadiusScale: 0.022,
  },
});
```

```ts
viewConfig(options?: ViewConfigOptions): void
```

#### `explodeView()` — Configure how the viewport explode slider offsets returned objects.

Offsets are resolved from the returned object tree, not a flat list. In `radial` mode each node follows its parent branch direction, then fans locally from the immediate parent center — nested assemblies peel apart level by level. In fixed-axis or fixed-vector modes, the branch follows that axis/vector but nested descendants fan out perpendicular by default.

Multiple calls merge — later values override earlier ones on a per-key basis. `byName` and `byPath` maps are merged entry-by-entry.

For programmatic explode applied before returning (without the slider), use `lib.explode()` instead.

```js
explodeView({
  amountScale: 1.2,
  stages: [0.35, 0.8],
  mode: 'radial',
  byPath: { 'Drive/Shaft': { direction: [1, 0, 0], stage: 1.6 } },
});
```

```ts
explodeView(options?: ExplodeViewOptions): void
```

**`ExplodeViewOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `enabled?` | `boolean` | Set false to disable viewport explode offsets for this script output. |
| `amountScale?` | `number` | Scales the UI explode amount. Default: 1 |
| `stages?` | `number[]` | Per-depth stage multipliers (depth 1 = first level). If depth exceeds this array, the last value is reused. Default when omitted: reciprocal depth (1, 1/2, 1/3, ...) |
| `mode?` | `ExplodeViewDirection` | Global direction mode fallback. Default: 'radial' |
| `axisLock?` | `ExplodeAxis` | Global axis lock fallback. |
| `byName?` | `Record<string, ExplodeViewDirective>` | Per-object overrides by final object name. |
| `byPath?` | `Record<string, ExplodeViewDirective>` | Per-tree-path overrides using slash-separated object tree segments. |

**`ExplodeDirective`**
- `stage?: number` — Multiplier applied to `amount` for this node
- `direction?: ExplodeDirection` — Direction mode for this node
- `axisLock?: ExplodeAxis` — Optional axis lock after direction is resolved

#### `jointsView()` — Register viewport-only mechanism controls that animate returned objects without re-running the script.

Defines joints (revolute or prismatic), optional gear/rack couplings, and named animations. The viewport resolves transforms through the joint chain at display time — the script geometry is computed only once at rest pose.

**Critical:** Solve the assembly at **rest pose** (all animated joints = 0). The viewport applies `jointsView` transforms on top of the returned scene. If geometry is already solved at non-zero angles, animation will double-rotate everything.

```js
// BAD — double rotation
const solved = mech.solve({ shoulder: 45, elbow: 30 });
jointsView({ joints: [{ name: 'shoulder', ... }] });
return solved;

// GOOD — rest pose, jointsView controls all posing
const solved = mech.solve({ shoulder: 0, elbow: 0 });
jointsView({
  joints: [
    { name: 'shoulder', child: 'Upper Arm', default: 45, ... },
    { name: 'elbow', child: 'Forearm', parent: 'Upper Arm', default: 30, ... },
  ],
});
return solved;
```

**Pivot coordinates** are world-space positions of each joint origin at rest pose. For `addRevolute('shoulder', 'Base', 'Link', { frame: Transform.identity().translate(0, 0, 20) })` where "Base" is at world origin, the pivot is `[0, 0, 20]`.

**Fixed attachments** that must follow a parent during animation need a zero-angle revolute joint in the chain:

```js
{ name: 'EE_Follow', child: 'End Effector', parent: 'Last Link',
  type: 'revolute', axis: [0, 0, 1], pivot: [linkLength, 0, 0],
  min: 0, max: 0, default: 0 }
```

Animation values are interpolated linearly between keyframes. ForgeCAD does **not** auto-wrap revolute values across `-180/180`. Keep keyframe values continuous — a `-180 -> 171` jump spins the part the long way around. Use `-180 -> -189` instead. Author high-speed multi-turn joints as accumulating angles (`0, 360, 720, ...`) with `continuous: true`.

**Tick-based keyframes:** Omit `at` from all keyframes to auto-distribute by tick weight:

```js
keyframes: [
  { ticks: 3, values: { Shoulder: 20 } },  // slow segment (3x weight)
  { ticks: 1, values: { Shoulder: -10 } }, // fast segment (1x weight)
  { values: { Shoulder: 20 } },            // last keyframe; ticks ignored
]
// positions: 0, 0.75, 1.0
```

Mixing explicit `at` and omitted `at` in the same animation is not allowed.

```js
jointsView({
  joints: [{
    name: 'Shoulder', child: 'Upper Arm', parent: 'Base',
    type: 'revolute', axis: [0, -1, 0], pivot: [0, 0, 46],
    min: -30, max: 110, default: 15,
  }],
  animations: [{
    name: 'Walk Cycle', duration: 1.6, loop: true,
    keyframes: [
      { values: { Shoulder: 20 } },
      { values: { Shoulder: -10 } },
      { values: { Shoulder: 20 } },
    ],
  }],
});
```

```ts
jointsView(options?: JointsViewOptions): void
```

**`JointsViewOptions`**: `enabled?: boolean`, `joints?: JointViewInput[]`, `couplings?: JointViewCouplingInput[]`, `animations?: JointViewAnimationInput[]`, `defaultAnimation?: string`

**`JointViewInput`**: `name: string`, `child: string`, `parent?: string`, `type?: JointViewType`, `axis?: JointViewAxis`, `pivot?: [ number, number, number ]`, `min?: number`, `max?: number`, `default?: number`, `unit?: string`, `hidden?: boolean`

`JointViewCouplingInput`: `{ joint: string, terms: JointViewCouplingTermInput[], offset?: number }`

`JointViewCouplingTermInput`: `{ joint: string, ratio?: number }`

`JointViewAnimationInput`: `{ name: string, duration?: number, loop?: boolean, continuous?: boolean, keyframes: JointViewAnimationKeyframeInput[] }`

**`JointViewAnimationKeyframeInput`**
- `at?: number` — Timeline position [0, 1]. If omitted from ALL keyframes, positions are auto-computed from tick weights.
- `ticks?: number` — Relative weight of the segment from this keyframe to the next (default 1). Only used in tick-based mode (when `at` is omitted). Last keyframe's ticks value is ignored.
- Also: `values: Record<string, number>`

#### `compareWith()` — Declare a reference model for comparison inspection.

`compareWith()` lets a model carry its own comparison target for inspection workflows. `forgecad inspect comparison model.forge.js` uses this reference to render the same Difference Only comparison overlay as the live viewport. Amber marks candidate mismatch evidence, cyan marks reference mismatch evidence, and faint model context keeps the overlay readable. When the CLI can resolve the referenced file, the manifest also includes the same geometric score produced by `forgecad compare 3d`.

The path is resolved relative to the file that calls `compareWith()`. It may point to another `.forge.js` file or an imported CAD asset such as `.stl`, `.obj`, `.3mf`, `.step`, or `.stp`.

```js
compareWith('./reference.3mf', { align: 'center', toleranceMm: 0.25, samples: 3000 });
return rebuiltBearing;
```

```ts
compareWith(path: string, options?: CompareWithOptions): void
```

**`CompareWithOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `align?` | `CompareAlignMode` | Candidate alignment before scoring. Defaults to no automatic alignment. |
| `toleranceMm?` | `number` | Distance tolerance in model units for coverage scoring. Defaults to the comparison scorer's auto tolerance. |
| `samples?` | `number` | Surface samples per direction for numeric scoring. Defaults to the comparison scorer's standard sample count. |
| `label?` | `string` | Human label for the reference model in inspection manifests. |

#### `cutPlane()` — Define a named section plane for inspecting internal geometry.

Registers a cut plane that appears as a toggle in the viewport View Panel. When enabled, geometry on the positive side of the plane (the side the normal points toward) is clipped away, revealing the internal cross-section. The newly exposed section faces render with a hatched overlay; pre-existing coplanar boundary faces are left unhatched.

Planes are registered once per script run. The viewport toggle state (on/off) persists across parameter changes without re-running the script. The `exclude` option only works correctly when the excluded object names are stable across parameter changes.

Accepts two overloads: `cutPlane(name, normal, offset?, options?)` or `cutPlane(name, normal, options?)` where options may include `offset`.

```js
const cutZ = param('Cut Height', 10, { min: -50, max: 50, unit: 'mm' });
cutPlane('Inspection', [0, 0, 1], cutZ, { exclude: ['Probe', 'Fasteners'] });
```

Overloads:

- `cutPlane(name: string, normal: [ number, number, number ], offset?: number, options?: CutPlaneOptions): void`
- `cutPlane(name: string, normal: [ number, number, number ], options?: CutPlaneOptions): void`

**`CutPlaneOptions`**
- `offset?: number` — Optional offset along the plane normal (primarily for object-form overload).
- `exclude?: CutPlaneExcludeInput` — Object names to keep uncut for this plane.

#### `mock()` — Register a mock (context) object for visualization and collision checking.

Mock objects appear in the viewport and spatial analysis when you run a file directly, but are excluded when the file is imported via [`require()`](/docs/core#require). This lets you model the surrounding context — walls, bolts, mating parts — without polluting the module's exports.

The shape is returned unchanged, so you can reference it for alignment, dimensioning, and `verify` checks.

Mock objects participate in `forgecad run --spatial bounded|exact` collision detection and spatial analysis. Their names appear with a `(mock)` suffix in reports.

In the viewport, mock objects render at reduced opacity so they are visually distinct from real geometry.

```ts
// bracket.forge.js
const wall = mock(box(100, 200, 10).translate(0, 0, -5), "wall");
const bolt = mock(cylinder(3, 15).translate(10, 15, 0), "bolt");

const bracket = box(20, 30, 5);
verify.notColliding("bracket vs wall", bracket, wall);

return bracket;
// When imported: only bracket is exported
// When run directly: bracket + wall + bolt all visible
```

```ts
mock<T extends Shape>(shape: T, name?: string): T
```

#### `showLabels()` — Highlight all user-labeled faces on a shape for visual debugging.

Shows each user-authored label name in the viewport for visual debugging. Returns the shape unchanged for chaining: `return showLabels(myShape)`.

```ts
showLabels(shape: Shape): Shape
```

#### `highlight()` — Highlight any geometry for visual debugging in the viewport.

Supported inputs:

- `string` — sketch entity ID (e.g. `'L0'`, `'P0'`, `'C0'`)
- `[x, y, z]` — 3D point
- `[[x1,y1,z1], [x2,y2,z2]]` — edge (line segment)
- `{ normal: [x,y,z], offset: number }` — plane by normal + distance from origin
- `{ normal: [x,y,z], point: [x,y,z] }` — plane by normal + point on plane
- [`Shape`](/docs/core#shape) — highlight entire 3D shape
- `FaceRef` (from `shape.face('top')`) — highlight as plane at face center
- `EdgeRef` (from `shape.edge('left')`) — highlight as edge segment

Overloads:

- `highlight(entityId: string, opts?: HighlightOptions): void`
- `highlight(point: [ number, number, number ], opts?: HighlightOptions): void`
- `highlight(edge: [ [ number, number, number ], [ number, number, number ] ], opts?: HighlightOptions): void`
- `highlight(plane: { normal: [ number, number, number ]; offset: number; }, opts?: HighlightOptions): void`
- `highlight(plane: { normal: [ number, number, number ]; point: [ number, number, number ]; }, opts?: HighlightOptions): void`
- `highlight(shape: Shape, opts?: HighlightOptions): void`
- `highlight(face: FaceRef, opts?: HighlightOptions): void`
- `highlight(edge: EdgeRef, opts?: HighlightOptions): void`

**`HighlightOptions`**
- `size?: number` — Size hint for points (radius in mm) or planes (disc radius in mm).
- Also: `color?: string, label?: string, pulse?: boolean`

**`FaceRef`**

| Option | Type | Description |
|--------|------|-------------|
| `normal` | `[ number, number, number ]` | Normal direction of the face |
| `center` | `[ number, number, number ]` | Center point of the face |
| `query?` | `FaceQueryRef` | Compiler-owned face query when available. |
| `planar?` | `boolean` | True when the face can host a 2D sketch placement frame |
| `uAxis?` | `[ number, number, number ]` | Face-local horizontal axis for planar faces |
| `vAxis?` | `[ number, number, number ]` | Face-local vertical axis for planar faces |
| `surface?` | `FaceSurface` | Analytic surface family when the backend can identify one. |
| `descendant?` | `FaceDescendantMetadata` | Shared descendant-resolution metadata when this face is a semantic region/set. |
| `name` | | — |

**`FaceDescendantMetadata`**: `kind: "single" | "face-set"`, `semantic: FaceDescendantSemantic`, `memberCount: number`, `memberNames: string[]`, `coplanar: boolean`

**`EdgeRef`**

| Option | Type | Description |
|--------|------|-------------|
| `start` | `[ number, number, number ]` | Start point |
| `end` | `[ number, number, number ]` | End point |
| `query?` | `EdgeQueryRef` | Compiler-owned edge query when available. |
| `curve?` | `EdgeCurve` | Exact or parametric curve family when the backend/source can identify one. |
| `faceName?` | `string` | Owning face name when the edge is associated with one face in a larger topology. |
| `name` | | — |

---

## Classes

### `RouteBuilder`

#### `up()` — Vertical line going +Y. Length is optional (solver determines it from constraints).

```ts
up(length?: number): LineId
```

#### `down()` — Vertical line going -Y. Length is optional.

```ts
down(length?: number): LineId
```

#### `right()` — Horizontal line going +X. Length is optional.

```ts
right(length?: number): LineId
```

#### `left()` — Horizontal line going -X. Length is optional.

```ts
left(length?: number): LineId
```

#### `lineAt()` — Line at an arbitrary angle (degrees from +X). Length is optional.

```ts
lineAt(angleDeg: number, length?: number): LineId
```

#### [`line()`](/docs/sketch#line) — Line with solver-determined direction. Length is optional. Direction comes from tangency to previous arc or from constraints.

```ts
line(length?: number): LineId
```

#### `toward()` — Line toward a specific point. Length defaults to the distance to that point.

```ts
toward(x: number, y: number): LineId
```

#### `arcLeft()` — Tangent arc turning left relative to travel direction.

or `{ minSweep: degrees }` to seed the geometry without constraining. `minSweep` guides the solver to the correct branch for arcs that sweep more than the default 90° seed.

```ts
arcLeft(radius?: number, sweepDegOrOpts?: number | { minSweep: number; }): ArcId
```

#### `arcRight()` — Tangent arc turning right relative to travel direction.

or `{ minSweep: degrees }` to seed without constraining.

```ts
arcRight(radius?: number, sweepDegOrOpts?: number | { minSweep: number; }): ArcId
```

#### `close()` — Close the route with a straight line back to the start point.

```ts
close(): void
```

#### `done()` — Close the route back to its start point and register as a profile loop.

No extra line segment is added. A coincident constraint connects the last point to the start, and tangency is added for G1 smoothness when arcs are at the junction. The session's incremental solver processes these constraints, keeping seed positions accurate for the final solve.

```ts
done(): void
```

#### `start()` — PointId of the route's start point.

```ts
get start(): PointId
```

#### `end()` — PointId of the current cursor (route's end).

```ts
get end(): PointId
```

#### `startOf()` — Get the start point of a segment.

```ts
startOf(segId: LineId | ArcId): PointId
```

#### `endOf()` — Get the end point of a segment.

```ts
endOf(segId: LineId | ArcId): PointId
```

---

## Constants

### `route`

Route step factories. Access via `route.line()`, `route.fillet()`, etc.

---

<!-- guides/modeling-recipes.md -->

# Modeling Recipes

## Iteration Bias

- Default to a buildable first pass instead of a long proposal.
- Replace a broken model wholesale when that is faster than incremental patching.
- Validate early with `forgecad run <file>`.

## Common Patterns

### Hollow Shell
```javascript
const innerSize = outer - 2 * wall;
const outerBox = box(outer, outer, outer).placeReference('center', [0, 0, 0]);
const innerBox = box(innerSize, innerSize, innerSize).placeReference('center', [0, 0, 0]);
return outerBox.subtract(innerBox);
```

### Sketch-Based Twist
```javascript
const outer = ngon(sides, radius);
const inner = ngon(sides, radius - wall);
return outer.subtract(inner).extrude(height, { twist: 45, divisions: 32 });
```

### Rounded Profiles
```javascript
// All convex corners — offset trick
const base = rect(50, 30).offset(-3, 'Round').offset(3, 'Round');

// Selected corners only
const roof = filletCorners(roofPoints, [
  { index: 3, radius: 19 },
  { index: 4, radius: 19 },
  { index: 5, radius: 19 },
]);
```

### Choosing the right sketch-rounding tool

- `offset(-r).offset(+r)` — round every convex corner of a closed outline
- `stroke(points, width, 'Round')` — centerline-based geometry (ribs, traces)
- `filletCorners(points, ...)` — selective true-corner fillets on mixed profiles

## Best Practices

- All dimensions in millimeters; angles in degrees.
- Primitives are centered on XY, base at Z=0. Use `placeReference('center', [0,0,0])` to center on all axes.
- Prefer named intermediate values over deeply nested one-liners.
- `union2d`, `difference2d`, `intersection2d` batch faster than chained `.add()` / `.subtract()`.

## Debugging

```javascript
console.log("Volume:", shape.volume());
```

For sketch-heavy work, compare the raw profile and rounded profile side-by-side before extruding:

```javascript
return [
  { name: "Raw", sketch: polygon(roofPoints) },
  { name: "Rounded", sketch: filletCorners(roofPoints, [...]).translate(120, 0) },
];
```

## Common Errors

- `"Kernel not initialized"` — internal/runtime issue, reload the app
- zero dimensions or self-intersecting sketches → invalid geometry
- wrong variable name → `"Cannot read property of undefined"`

For deeper API coverage, load the relevant generated doc group from the skill source map instead of reaching for repo examples by default.

---

<!-- guides/joint-design.md -->

# Joint Design Recipes

How to build mechanical joints — clevis-tongue hinges, ball-and-socket, dovetails — that actually rotate without binding and stop where they should.

## The Cavity Rule

Every mechanical joint has a **cavity** in one part and a **tenon** in the other. The cavity must be a real empty volume — not a gap implied by the absence of two separate solids.

If two adjacent parts in an assembly show a collision volume larger than the expected clearance volume in `forgecad run`, one part is missing its cavity. Both parts have solid material at the same joint position. This will look fine at rest pose but will block rotation and produce confusing joint behavior.

```ts
// BAD — body has a stadium cap at both ends; the "slot" between two clevis tines
// is just empty space next to a solid body cap. The next phalanx's tongue knuckle
// has nowhere to go (it intersects the previous body's cap).
const body  = stadiumBar(L);            // cap at X=0 AND X=L
const tine1 = box(...).translate(L,  Y_OFF, 0);
const tine2 = box(...).translate(L, -Y_OFF, 0);
let phalanx = union(body, tine1, tine2);

// GOOD — body ends FLAT before the joint. Tines extend forward to the pivot.
// The X = L-KNUCK_R..L+KNUCK_R volume between the tines is genuinely empty.
const body = box(L - KNUCK_R, TONG_T, H).translate((L - KNUCK_R) / 2, 0, -H / 2);
const tongueKnuckle = knuckleDisc(0, 0, TONG_T);  // proximal cap only
let phalanx = union(tongueKnuckle, body, tine1, tine2, ...tineCaps);
```

After applying the cavity rule, `forgecad run` collision volume between adjacent parts in a clevis-tongue chain should drop to **zero** (or a few mm³ of clearance overlap). If it doesn't, there's still solid material where there should be a cavity.

## Connecting Cantilevers

A clevis tine arm at Y=±Y_OFF is geometrically separate from a body at Y=±TONG_T/2. With Y_OFF > TONG_T/2 + clearance, there is a **physical gap** between them. The tines float — they would snap off as soon as load is applied.

Always add a **yoke**: a short slab spanning the full clevis width, sitting between the body's flat distal end and the tines' attachment point. The yoke fills the Y gap so material is continuous from the body through to each tine.

```ts
const yokeLen   = 3;                                  // a few mm of structural overlap
const yokeStart = L - KNUCK_R - yokeLen;
const totalY    = (Y_OFF + TINE_T / 2) * 2;           // full clevis width
const yoke = box(yokeLen, totalY, H)
  .translate(yokeStart + yokeLen / 2, 0, -H / 2);
phalanx = union(phalanx, yoke);
```

## Hard Stops vs Slider Limits

`addRevolute({ min: 0, max: 90 })` sets **slider limits** — the viewport won't let the user drag past them, but the geometry permits any rotation. There is no physical stop.

For a **geometric** hard stop (parts can't backbend past extension, or can't curl past full closure), add a small protrusion on one part that interferes with the other at the limit angle:

- **Extension stop at 0°** (typical for fingers, knees, elbows): add a small "lip" on the dorsal side of the proximal end of the child phalanx, sized so it just touches the parent's distal dorsal corner at 0°. Negative rotation (backbending) is then blocked by part-on-part contact.
- **Flexion stop at θmax**: add a similar lip on the palmar side, or rely on the body-to-body collision when bodies meet.

Verify with `forgecad run` at the limit poses — the contact pair should show ~0 mm³ collision (just touching), and rotation past the limit should report a non-zero collision volume.

## Knuckle Sizing

For a clevis-tongue joint with body height H, the tongue knuckle radius and clevis tine knuckle radius must satisfy:

```
KNUCK_R >= H / 2
```

If the knuckle radius is smaller than the body's half-height, the body's corners protrude beyond the knuckle envelope. When the joint rotates, those corners sweep through space outside the cylindrical envelope and collide with the adjacent part.

Setting `KNUCK_R = H / 2` exactly makes the body cross-section a stadium that perfectly fits the knuckle envelope.

## Verification Workflow

1. Build the joint at rest pose. Run `forgecad run`. Check collision volumes.
2. If adjacent parts in the joint show > clearance-volume of overlap → missing cavity (apply the cavity rule).
3. Render with `--focus PartName` to inspect each part in isolation. The clevis end should clearly show a gap between the tines (the cavity).
4. Render at curl angles (set joint debug params) at 30°, 60°, 90°. No new collisions should appear from rotation.
5. Render at -10° (backbend test). Either no rotation possible (geometric stop in place) or rotation occurs and you need to add a stop.

---

<!-- guides/inspection-bundles.md -->

# Inspection Bundles

`forgecad inspect <evidence>` writes a deterministic directory bundle for
agents, tests, and automation. Use it when a single shaded PNG is too ambiguous
and the consumer needs geometry-aware evidence such as depth, normals, Zebra
stripes, surface roughness, part identity, physical connected components,
collisions, local thickness, or cross-sections.

## When To Use It

- Use `forgecad inspect <evidence>` for local agent repair loops, model
  debugging, and targeted visual evidence.
- Use `forgecad render 3d` for a quick human viewport PNG.
- Use `forgecad render section` when you only need one specific cut plane.
- Use `forgecad render hq` for presentation-quality output, docs, and marketing
  renders.

## Command

```bash
forgecad inspect collisions model.forge.js --camera iso
forgecad inspect objects model.forge.js --camera front --camera right
forgecad inspect thickness model.forge.js --min 1.2 --warn 2.0
forgecad inspect sections model.forge.js
forgecad inspect comparison model.forge.js --with reference.3mf
forgecad inspect evidence
```

The default output directory is `<script-name>-<evidence>-inspect/` next to the
input file. A bare command emits one `iso` view. Pass `--camera` repeatedly,
`--view`, `--camera-json`, or `--scene` to use the same view strategy as
`render 3d`. Pass `--force` to replace an existing bundle directory.

`--focus` and `--hide` use the same object-name filtering semantics as
`forgecad run` and `forgecad render 3d`. A bare `--focus` hides mock objects;
`--focus name1,name2` emits only matching objects; `--hide name1,name2` removes
matching objects from an otherwise visible scene. Matching is case-insensitive
and supports `*` / `?` globs, so grouped child objects are usually best matched
with patterns such as `Bench.*`.

## Bundle Layout

Bundles store image evidence under an `evidence/` directory. An
`inspect objects` bundle with `front`, `right`, and `iso` cameras has this
layout:

```text
model-objects-inspect/
  manifest.json
  evidence/
    objects/
      front.png
      right.png
      iso.png
```

Use targeted evidence commands for expensive analyses:

```bash
forgecad inspect depth model.forge.js --camera iso
forgecad inspect normals model.forge.js --camera iso
forgecad inspect zebra model.forge.js --camera iso
forgecad inspect roughness model.forge.js --camera iso
forgecad inspect objects model.forge.js --camera iso
forgecad inspect collisions model.forge.js --camera iso
forgecad inspect sections model.forge.js
forgecad inspect thickness model.forge.js --min 1.2 --warn 2.0 --camera iso
forgecad inspect comparison model.forge.js --with reference.3mf
```

Supported evidence commands are `image`, `depth`, `normals`, `zebra`,
`roughness`, `objects`, `connectivity`, `floating`, `distance`, `comparison`,
`collisions`, `thickness`, and `sections`. The same names are used in
`manifest.evidence`.

## How To Read A Bundle

Read inspection bundles as feedback about the model, not as standalone images.
Start with `manifest.json`, then use the evidence PNGs to locate and understand
the finding in the rendered geometry.

1. Confirm `bundle.evidenceRequested`, `bundle.evidenceEmitted`, and
   `bundle.filters` so you know what was inspected and what was hidden.
2. Check `scene.bbox`, `scene.volume`, and `scene.objects` for missing geometry,
   absurd scale, unexpected mocks, or wrong object names.
3. For identity evidence such as `objects`, `connectivity`, `distance`, and
   `collisions`, resolve colors through the evidence manifest. The same visual
   color does not carry a universal meaning across bundles.
4. For metric evidence such as `depth`, `roughness`, `thickness`, `distance`, and `comparison`,
   read the thresholds, ranges, object summaries, and warnings before judging a
   PNG by eye.
5. Inspect image and object evidence first when you need visual context, then
   the risk evidence and any orthographic view that exposes the issue. Use
   section slices only to inspect hidden internals; do not turn the production
   model into a permanent cutaway.
6. Treat unexpected collisions, critical thin regions, unresolved thickness,
   missing section detail, wrong component counts, floating bodies, or surprising
   distance gaps as model bugs to fix and reinspect.

Common color reading rules:

- Black is usually background; in `floating`, black also means ground-reachable
  geometry.
- `objects` and `connectivity` colors are labels. Use the manifest to map colors to
  objects, groups, components, or body entries.
- `collisions` colors mark solid overlap findings; match them to
  `manifest.evidence.collisions.collisions[].color`.
- `thickness` uses red/orange for critical or warning-thin regions, green/blue
  for acceptable or thick regions, and gray for unresolved samples.
- `distance` grades rooted component gaps from green near the root through
  yellow to red farther away.
- `comparison` uses the same Difference Only overlay as the viewport: faint
  model context, amber candidate mismatch evidence, and cyan reference mismatch
  evidence.
- `depth` grades visible camera distance from blue near the camera through green
  to red farther away.
- `roughness` uses orange and magenta for sharp, harsh, boundary, or
  non-manifold edge neighborhoods.
- `zebra` is read by stripe continuity: smooth flowing bands are healthy, while
  kinks, breaks, and faceting deserve investigation.
- `normals` is an encoded camera-view normal map. Use it with `image` and `zebra`
  to debug orientation and faceting rather than as a fixed semantic palette.

## Evidence Semantics

`image` emits the standard solid viewport render with a thin edge overlay. Views
are canonical `front`, `right`, `top`, and `iso`.

`depth` emits visible ray-distance heatmaps. Each shaded pixel is colored by the
distance from the camera position to the visible surface point, normalized per
view between `minDistance` and `maxDistance` from the manifest:

```text
rayDistance = distance(cameraPosition, surfacePoint)
normalized = (rayDistance - minDistance) / (maxDistance - minDistance)
```

The ramp is blue near the camera, green in the middle, and red far from the
camera. Background pixels are black and should be treated as `null`.

`normals` emits camera-view normals packed into RGB:

```text
normal = normalize((rgb / 255) * 2 - 1)
```

Background pixels are black and should be treated as `null`.

`zebra` emits reflective black-and-white stripe renders for visual
surface-continuity inspection. Stripes are generated from the visible
camera-view normal and simulated reflection direction, so smooth surfaces show
smooth flowing bands while normal discontinuities, faceting, and unexpected
creases kink or break the bands.

Use Zebra with `image` and `normals` when judging lofts, fillets, swept surfaces,
and skin-like forms. It is a human-readable shader diagnostic, not an exact
curvature-continuity proof; mesh tessellation quality and available smooth
normals determine how faithfully it represents the underlying surface.

`roughness` emits a mesh-dihedral surface-quality heatmap. Smooth and gently
curved triangles render as a faint translucent shadow over black, while
triangles adjacent to sharp, harsh, boundary, or non-manifold mesh edges render
in orange or magenta:

```text
shadow  = max adjacent angle < sharpAngleDeg
orange  = sharpAngleDeg <= angle < harshAngleDeg
magenta = angle >= harshAngleDeg, boundary, or non-manifold
```

The default thresholds are `smoothAngleDeg=5`, `sharpAngleDeg=30`, and
`harshAngleDeg=90`. The manifest stores the method, thresholds, palette, object
list, per-object triangle and edge counts, area percentages by smooth,
moderate, sharp, and harsh classes, angle percentiles, maximum angle, quality
score, and warnings. Moderate angles are reported in the manifest but stay in
the shadow layer by default so intentionally curved surfaces do not light up as
defects. Use this evidence to spot spiky tessellation, accidental faceting,
jagged boolean residue, and dense sharp-corner regions without losing the
silhouette of otherwise smooth surfaces.

The evidence also writes `evidence/roughness/point-cloud.json`. Each point sample
stores object identity, object-local position, normal, dihedral angle, class,
RGB color, and represented surface area. The PNG renders those samples over
muted source geometry so the visual evidence stays point-level instead of
painting a whole object.

`objects` emits one object-color image per view. Black is background. Non-black
pixels resolve through `manifest.evidence.objects.objects`, which includes object
index, RGB color, object id, name, group, tree path, and mock flag. Edge pixels
may be antialiased blends; use solid interior colors for exact object lookup.

`connectivity` emits one physical-component-color image per view. Black is
background. Non-black pixels resolve through
`manifest.evidence.connectivity.components`, and every visible object also has a
`componentIndex` in `manifest.evidence.connectivity.objects`.

Connectivity is computed from visible scene objects:

```text
bbox candidate = bbox interiors overlap or bbox contact gap <= 0.05 model units
mesh contact edge = minimum mesh-surface distance <= contactTolerance
overlap edge = exact boolean intersection volume > 0.1 model units^3 for positive-volume overlap
component = transitive closure over mesh contact and exact overlap edges
```

The manifest stores the edge list, component list, per-object body counts, and
warnings. Component colors group scene objects and mesh body entries. If one
scene object contains multiple disconnected mesh islands, those islands are
reported and colored separately as entries such as `Part body 1` and
`Part body 2`.

Connectivity uses bbox only as a broadphase. Bbox contact alone is not enough to
merge separate scene objects by default, but mesh surfaces within contact
tolerance count as physically connected. This keeps concave assemblies such as
cages and captive balls from being falsely colored as one component while still
allowing stacked or nearly touching parts to share a component. Use the
`collisions` evidence when you need positive-volume overlap evidence as a defect
report rather than a component grouping.

`floating` emits one disconnected-body highlight image per view. Black is
background or ground-reachable geometry. The highlight color marks physical
components that have no contact path to the ground plane.

Floating body detection splits visible meshes into disconnected body islands,
links bodies only when their minimum mesh-surface distance is within contact
tolerance (or exact positive-volume overlap when only shape evidence is
available), treats any connected component whose lower Z reaches the viewport
ground plane plus bed tolerance as grounded, then highlights every ungrounded
component. The default ground plane is the visible model's minimum Z;
`scene({ ground: { offset } })` moves it below that by the configured offset.

```text
grounded = component bbox minZ <= groundZ + bedTolerance
floating body = !grounded
```

This means a `union()` result with two disconnected mesh islands is inspected as
two separate bodies instead of being treated as one safe object. Bbox overlap or
bbox face contact alone is not support evidence. Use `connectivity`, `distance`,
or `collisions` when you need the full physical graph, rooted gap distances, or
collision defects.

`distance` emits one rooted physical-component-distance heatmap per view. Black
is background. Non-black pixels resolve through
`manifest.evidence.distance.components`, and every visible object also has
`componentIndex`, `rootDistance`, `nearestGap`, and parent-tree metadata in
`manifest.evidence.distance.objects`.

Distance is computed from visible scene objects:

```text
component = physical connectivity component
gap edge = Euclidean distance between component bounding boxes
root = largest component by body count, object count, then bbox volume
rootDistance = shortest accumulated gap distance from root component
```

For large scenes the manifest does not materialize the complete component gap
graph, because that graph is quadratic in the number of components. The
`gapEdgeCount` field reports the logical complete-graph edge count used by the
analysis. `gapEdges` stores a compact evidence subset containing nearest-gap
and root-parent edges.

The PNG colors components from green at the root/near distances through yellow to
red at the farthest rooted component. The manifest stores the root component,
maximum rooted distance, compact gap edge evidence, nearest-gap data, and
shortest-path parent fields. The current v1 metric is bbox-based: it measures air
gaps between component bounding boxes, not exact closest mesh-surface distance.

`comparison` emits one reference-vs-candidate overlay per view. Pass
`--compare-with <reference>` or declare the target in model code with
`compareWith('./reference.3mf')`. The PNG uses the same Difference Only
comparison overlay as the viewport. Amber marks candidate mismatch evidence,
cyan marks reference mismatch evidence, and faint candidate/reference context
keeps the overlay readable while rotating or comparing against the standard RGB
render.

Colored mismatch evidence comes from sampled nearest-surface distances: cyan
means reference surface missing from the candidate, and amber means extra
candidate surface. Run `forgecad inspect sections` when you also want the
explicit principal-plane cut atlas next to the comparison context views.

The manifest stores visual screen-space mismatch counts, the geometric
`compare 3d` score when the CLI can resolve both inputs, and a
`evidence/comparison/mismatch-points.json` point cloud with world-space sample
positions. Use the geometric score and point-cloud summary as the source of
truth; the PNG is the fast visual index for where to look.

`collisions` emits one ghosted-overlap image per view. It uses the same
`--focus` / `--hide` visibility set as every other inspect evidence: focused
objects are the only inspected objects. Source objects render as translucent
ghosts, while actual boolean intersection volumes render as solid per-finding
palette colors.

Collision findings are computed from visible scene objects:

```text
collision = boolean intersection volume > 0.1mm^3
```

The manifest stores the inspected objects, collision pair names/ids, overlap
volume, broadphase counters, warnings, render style, and each collision finding's
`groupIndex`, `color`, and `hex`. Exact interior pixels can be matched against
`manifest.evidence.collisions.collisions[].color`; antialiased edges may blend
with the ghosted source geometry. If `--focus PartA,PartB` is used, everything
except those objects is hidden, `PartA` and `PartB` are ghosted, and their
overlap volume is highlighted if present.

Collision broadphase prunes exact boolean checks when the bbox intersection
volume is already below the overlap threshold. This does not change findings:
the real intersection volume cannot exceed the bbox intersection volume.

`thickness` emits one local wall-thickness heatmap per view. The renderer places
deterministic area-weighted point samples across visible mesh surfaces, casts
through the object along each sample normal, and colors each point by the first
opposite-surface distance:

```text
red    = thickness <= minThickness
orange = thickness <= warnThickness
green  = acceptable thickness
blue   = thickness >= maxThickness
gray   = unresolved sample
```

Thickness uses the same physical-contact edges as `connectivity` and `floating`.
When a ray crosses from one object to a direct physical-contact neighbor, hits
within `contactTolerance` are treated as contact seams and the ray continues to
the next surface. This prevents a tiny modeled gap between touching parts from
being reported as a paper-thin wall.

The default thresholds are `minThickness=1.2`, `warnThickness=2.0`, and
`maxThickness=6.0` model units. Override them with `--min-thickness`,
`--warn-thickness`, and `--max-thickness`. Use `--thickness-samples` to raise or
lower the maximum thickness point samples per object.

The manifest stores the method, thresholds, palette, object list, per-object
triangle counts, sampled-triangle counts, minimum, p05, median, mean, maximum,
critical-area percentage, warning-area percentage, below-warning percentage, and
unresolved-area percentage. This makes the PNG useful for visual debugging while
the manifest remains the machine-readable source of truth.

The evidence also writes `evidence/thickness/point-cloud.json`. Each point sample
stores object identity, object-local position, normal, measured thickness,
class, RGB color, and represented surface area. The PNG renders those samples
over muted source geometry, so local evidence survives even when neighboring
triangles have very different values.

`roughness` uses the same area-weighted point placement. Point colors are local
to nearby physical feature edges: smooth tessellation diagonals do not become
visible roughness lines. Use `--roughness-samples` to raise or lower the maximum
roughness point samples per object.

`sections` emits five interior slices per principal plane. The current slicing
policy is:

```text
offset = bbox.min[axis] + fraction * (bbox.max[axis] - bbox.min[axis])
fractions = [1/6, 2/6, 3/6, 4/6, 5/6]
planes = xy, xz, yz
```

Each section slice records its exact offset, fraction, area, path count, size,
and contributing object count in the manifest.

## Manifest

`manifest.json` is the authoritative contract for consuming a bundle. It
contains:

- `schemaVersion` and generator metadata.
- Source entry file and project root paths.
- Requested evidence, emitted evidence, filters, image size, and quality.
- Canonical views.
- Scene metadata: bbox, volume, params, cut planes, animations, verifications,
  and objects.
- Evidence metadata and relative file paths.

A consumer should prefer paths from the manifest over hard-coding bundle layout.
The layout is intentionally simple, but the manifest is where encoding details,
per-view depth ranges, and object identity mappings live.

## Current Limits

- Depth is a visual heatmap, not an EXR or raw float array.
- Normals are camera-view normals, not world-space normals.
- Object evidence colors are stable within a bundle and resolved through the manifest; do
  not infer identity from object order alone.
- Connectivity is object-level. It reports disconnected kernel bodies in the
  manifest, but the PNG does not split a single scene object into per-body colors.
- Bbox contact is only broadphase evidence and does not merge separate scene
  objects by default. Boolean-overlap edges are exact.
- Distance is a physical-component bbox-gap metric in v1, not exact nearest
  mesh-surface distance. Concave components and loose bounding boxes can make the
  reported gap smaller than the real closest-surface distance.
- Comparison PNG coverage is screen-space evidence. Hidden or internal
  mismatches need the sampled point cloud and geometric score in the manifest.
- Collisions are only positive-volume boolean overlaps. Face-touching parts are
  not collision findings.
- Thickness is a mesh/raycast approximation, not FEA or a manufacturability
  guarantee. Open meshes, concave geometry, very coarse tessellation, or low
  `--thickness-samples` values can leave gray/unresolved or approximate regions.
- Section atlases use five default interior slices today.
- Zebra is a shader-based visual continuity aid, not exact curvature analysis.

---

<!-- generated/sdf.md -->

# SDF Modeling

Signed Distance Field modeling for organic forms, smooth booleans, TPMS lattices, and deformations. SDFs are inherently implicit fields, not B-rep/exact geometry; use them with caution when precision or exact export matters. Return raw `SdfShape` values directly for native preview; use `toShape(...)` when materializing SDF trees for CAD/export workflows.

## Contents

- [SDF Materialization](#sdf-materialization) — `toShape`, `combine`
- [SdfShape](#sdfshape)
- [sdf](#sdf)
- [Sculpt](#sculpt)

## Functions

### SDF Materialization

#### `toShape()` — Materialize one SDF leaf or all SDF leaves in a renderable tree.

Raw `SdfShape` values become mesh-backed [`Shape`](/docs/core#shape)s. Plain objects and arrays preserve their renderable children as a [`ShapeGroup`](/docs/core#shapegroup) when more than one leaf is found. Non-renderable metadata is ignored for materialization and remains available to callers through normal [`require()`](/docs/core#require) return values.

```ts
toShape(value: unknown, options?: SdfToShapeOptions): ToShapeTreeResult
```

**`SdfToShapeOptions`**

| Option | Type | Description |
|--------|------|-------------|
| `edgeLength?` | `number` | Target mesh edge length. Smaller = finer mesh. Overrides quality-derived resolution. |
| `bounds?` | `{ min: Vec3; max: Vec3; }` | Override auto-computed bounds. Strongly recommended for infinite/repeated fields. |
| `quality?` | `SdfMeshingQuality` | Coarse quality preset. Default: 'preview'. |
| `tolerance?` | `number` | Preferred absolute surface tolerance in millimeters. |
| `minFeatureSize?` | `number` | Smallest feature that should survive meshing, in millimeters. |
| `simplify?` | `boolean \| "safe"` | Simplification control. `false` disables, `true` and `'safe'` use topology-validated simplification. |
| `maxTriangles?` | `number` | Optional post-extraction triangle budget. |
| `maxGridPoints?` | `number` | Optional pre-extraction grid-point budget. Default is browser-safe. |
| `minEdgeLength?` | `number` | Lower clamp for resolved edge length. Default: 0.15mm. |
| `diagnostics?` | `boolean` | Log resolved meshing settings and backend extraction timings. |

#### `combine()` — Collapse a tree of SDF leaves into one continuous SDF field.

This intentionally discards per-leaf color/material identity because the result is one scalar field. Use plain object returns for multi-material SDF preview, and use `combine(...)` only when you want one implicit body.

```ts
combine(value: unknown, options?: CombineOptions): SdfShape
```

`CombineOptions`: `{ op?: "union" | "intersection" }`

---

## Classes

### `SdfShape`

An immutable SDF expression. Supports SDF-specific operations (smooth booleans, domain warps, etc.), can be returned directly for native preview, and converts to a ForgeCAD Shape via `.toShape()` when materialization is needed.

#### `colorHex()` — Display color carried by this implicit leaf.

```ts
get colorHex(): string | undefined
```

#### `materialProps()` — Display material carried by this implicit leaf.

```ts
get materialProps(): ShapeMaterialProps | undefined
```

#### `explicitBounds()` — Explicit bounds carried by this implicit leaf, if any.

```ts
get explicitBounds(): SdfBounds | undefined
```

#### `clone()` — Clone this SDF expression and its visual metadata.

```ts
clone(): SdfShape
```

#### `toShape()` — Mesh this SDF into a ForgeCAD Shape through ForgeCAD's Surface Nets pipeline. Once converted, the result is a regular Shape — booleans, transforms, export all work.

```ts
toShape(options?: SdfToShapeOptions): Shape
```

#### `color()` — Set the display color for this implicit leaf.

```ts
color(value: string | undefined): SdfShape
```

#### `material()` — Set PBR display material properties for this implicit leaf.

```ts
material(props: ShapeMaterialProps): SdfShape
```

#### `bounds()` — Set explicit preview/meshing bounds for this implicit leaf.

```ts
bounds(bounds: SdfBounds | [ Vec3, Vec3 ]): SdfShape
```

#### `at()` — Sculpt-style alias for translate().

```ts
at(x: number, y: number, z: number): SdfShape
```

#### `move()` — Sculpt-style alias for translate().

```ts
move(x: number, y: number, z: number): SdfShape
```

#### `spin()` — Sculpt-style alias for rotateZ().

```ts
spin(angleDeg: number): SdfShape
```

#### `tilt()` — Sculpt-style tilt around X, Y, Z, or a custom axis.

```ts
tilt(angleDeg: number, axis?: "x" | "y" | "z" | Vec3): SdfShape
```

#### `round()` — Sculpt-style rounded-box helper. Currently applies directly to primitive SDF boxes.

```ts
round(radius: number): SdfShape
```

#### `blend()` — Sculpt-style smooth blend with another implicit shape.

```ts
blend(other: SdfShape, options?: number | { radius?: number; }): SdfShape
```

#### `goop()` — Sculpt-style alias for blend().

```ts
goop(other: SdfShape, options?: number | { radius?: number; }): SdfShape
```

#### `carve()` — Sculpt-style smooth carve/subtract.

```ts
carve(other: SdfShape, options?: number | { radius?: number; }): SdfShape
```

#### `keep()` — Sculpt-style smooth intersection/keep operation.

```ts
keep(other: SdfShape, options?: number | { radius?: number; }): SdfShape
```

#### `polish()` — Apply a Sculpt material preset or direct material props.

```ts
polish(input?: SculptPolishInput): SdfShape
```

#### [`union()`](/docs/core#union) — SDF union (sharp).

```ts
union(...others: SdfShape[]): SdfShape
```

#### `subtract()` — SDF difference (sharp) — subtracts others from this.

```ts
subtract(...others: SdfShape[]): SdfShape
```

#### `intersect()` — SDF intersection (sharp).

```ts
intersect(...others: SdfShape[]): SdfShape
```

#### `clipBox()` — Clip this SDF to an explicit box-shaped design space.

```ts
clipBox(x: number, y: number, z: number): SdfShape
```

#### `fillWith()` — Keep only the material where this shape overlaps another SDF pattern.

```ts
fillWith(pattern: SdfShape): SdfShape
```

#### `fillWithGyroid()` — Keep only the gyroid lattice inside this shape.

```ts
fillWithGyroid(options: TpmsOptions): SdfShape
```

#### `fillWithSchwarzP()` — Keep only the Schwarz-P lattice inside this shape.

```ts
fillWithSchwarzP(options: TpmsOptions): SdfShape
```

#### `fillWithDiamond()` — Keep only the diamond TPMS lattice inside this shape.

```ts
fillWithDiamond(options: TpmsOptions): SdfShape
```

#### `fillWithLidinoid()` — Keep only the lidinoid TPMS lattice inside this shape.

```ts
fillWithLidinoid(options: TpmsOptions): SdfShape
```

#### `smoothUnion()` — Smooth union — blends shapes together with a smooth radius.

```ts
smoothUnion(other: SdfShape, radius: number): SdfShape
```

#### `smoothSubtract()` — Smooth difference — smoothly carves other from this.

```ts
smoothSubtract(other: SdfShape, radius: number): SdfShape
```

#### `smoothIntersect()` — Smooth intersection — smoothly intersects.

```ts
smoothIntersect(other: SdfShape, radius: number): SdfShape
```

#### `morph()` — Morph between this shape and another. t=0 → this, t=1 → other.

```ts
morph(other: SdfShape, t: number): SdfShape
```

#### `translate()` — Translate this SDF by the given offsets in millimeters.

```ts
translate(x: number, y: number, z: number): SdfShape
```

#### `rotate()` — Rotate around an arbitrary axis through the origin.

```ts
rotate(axis: [ number, number, number ], angleDeg: number): SdfShape
```

#### `rotateX()` — Rotate around the X axis by the given angle in degrees.

```ts
rotateX(angleDeg: number): SdfShape
```

#### `rotateY()` — Rotate around the Y axis by the given angle in degrees.

```ts
rotateY(angleDeg: number): SdfShape
```

#### `rotateZ()` — Rotate around the Z axis by the given angle in degrees.

```ts
rotateZ(angleDeg: number): SdfShape
```

#### `scale()` — Uniformly scale this SDF around the origin.

```ts
scale(factor: number): SdfShape
```

#### `twist()` — Twist around the Z axis.

```ts
twist(degreesPerUnit: number): SdfShape
```

#### `bend()` — Bend around the Z axis with given radius.

```ts
bend(radius: number): SdfShape
```

#### `repeat()` — Repeat in space. Spacing of 0 on an axis means no repetition. Count of 0 = infinite.

```ts
repeat(spacing: Vec3, count?: Vec3): SdfShape
```

#### `circularArray()` — Arrange this SDF in a circular array around the Z axis.

The source shape is translated by `offset` in +X before arraying. This uses angular domain folding, so evaluation stays O(1): the source SDF is sampled twice no matter how many copies are requested.

```ts
circularArray(count: number, offset?: number): SdfShape
```

#### `shell()` — Hollow out, keeping only a shell of given thickness.

```ts
shell(thickness: number): SdfShape
```

#### `displace()` — Displace the surface by a function of position, or by a pattern SdfShape.

```js
// Function displacement
shape.displace((x, y, z) => Math.sin(x) * 0.5)

// Pattern displacement from a 3D SDF field
shape.displace(sdf.knurl({ pitch: 2, depth: 0.3 }))
```

```ts
displace(fn: ((x: number, y: number, z: number) => number) | SdfShape, constants?: Record<string, number>): SdfShape
```

#### `surfaceDisplace()` — Displace the surface using a 2D pattern in surface-local UV coordinates.

Automatically detects the shape's UV parametrization (sphere, cylinder, torus) from the SDF tree. Falls back to triplanar mapping for arbitrary shapes.

UV coordinates are in **surface millimeters** — patterns defined with `spacing: 3` always produce 3mm spacing, regardless of shape size.

Prefer `sdf.pattern2d()` or built-in surface patterns when the relief should stay on the native shader and meshing path. Callback functions are supported for experimentation, but they are opaque to the typed pattern optimizer.

```js
// Native typed pattern — auto-detects sphere UV
const p = sdf.pattern2d()
const ribs = p.stripes({ spacing: 3, width: 0.8, depth: 0.35 })
  .add(p.sineWave({ direction: [0, 1], wavelength: 14, amplitude: 0.08 }))

sdf.sphere(27).shell(3)
  .surfaceDisplace(ribs)
  .toShape()

// Custom 2D pattern via function
shape.surfaceDisplace((u, v) => -Math.sin(u * 2) * 0.3)
```

```ts
surfaceDisplace(pattern: SurfacePattern | ((u: number, v: number) => number), options?: SurfaceDisplaceOptions): SdfShape
```

#### `onion()` — Create concentric onion layers.

```ts
onion(layers: number, thickness: number): SdfShape
```

---

## Constants

### `sdf`

SDF modeling — signed distance field primitives, smooth booleans, TPMS lattices, domain warps, and surface patterns.

Return `SdfShape` values directly from a ForgeCAD script for native raymarch preview. Plain objects and arrays of SDF leaves are renderable too, so object keys become named preview parts.

Call `.toShape()` or `toShape(...)` only when you need a mesh-backed ForgeCAD Shape for export, mesh booleans, or mixed SDF/manifold projects. All shapes live as a lazy expression tree until that materialization boundary.

SDF is inherently implicit and sampled, not B-rep/exact geometry. Use it with caution when precision, tolerances, or exact export matter.

```js
return sdf.smoothUnion(sdf.sphere(10), sdf.box(15, 15, 15), { radius: 3 })
  .color('#4488cc');
```

```js
return {
  shell: sdf.sphere(20).shell(2).color('#9be7ff'),
  core: sdf.gyroid({ cellSize: 6, wallThickness: 0.8 })
    .intersect(sdf.sphere(18))
    .color('#ffcf5a'),
};
```

- `sphere(radius: number): SdfShape` — Create an SDF sphere centered at the origin.
- `box(x: number, y: number, z: number): SdfShape` — Create an SDF box centered at the origin with given full dimensions (not half-extents).
- `cylinder(height: number, radius: number): SdfShape` — Create an SDF cylinder centered at the origin, axis along Z.
- `torus(majorRadius: number, minorRadius: number): SdfShape` — Create an SDF torus centered at the origin, lying in the XY plane.
- `capsule(height: number, radius: number): SdfShape` — Create an SDF capsule centered at the origin, axis along Z.
- `cone(height: number, radius: number): SdfShape` — Create an SDF cone with base at z=0 and tip at z=height.
- `smoothUnion(a: SdfShape, b: SdfShape, options: { radius: number; }): SdfShape` — Smooth union — blends shapes together with a smooth transition radius.
- `smoothDifference(a: SdfShape, b: SdfShape, options: { radius: number; }): SdfShape` — Smooth difference — smoothly subtracts b from a.
- `smoothIntersection(a: SdfShape, b: SdfShape, options: { radius: number; }): SdfShape` — Smooth intersection — smoothly intersects a and b.
- `morph(a: SdfShape, b: SdfShape, t: number): SdfShape` — Morph between two SDF shapes. t=0 → a, t=1 → b.
- `blend(a: SdfShape, b: SdfShape, fn: (x: number, y: number, z: number) => number, options?: BlendOptions): SdfShape` — Spatially blend between two SDF patterns. The blend function receives (x, y, z) and returns 0..1: 0 = fully pattern `a`, 1 = fully pattern `b`.
- `gyroid(options: TpmsOptions): SdfShape` — Gyroid TPMS lattice — the most common lattice for additive manufacturing.
- `schwarzP(options: TpmsOptions): SdfShape` — Schwarz-P TPMS lattice — isotropic pore structure.
- `diamond(options: TpmsOptions): SdfShape` — Diamond TPMS lattice — stiffest TPMS structure.
- `lidinoid(options: TpmsOptions): SdfShape` — Lidinoid TPMS lattice — visually distinct from gyroid, popular in research and art.
- `tpmsBlock(options: TpmsBlockOptions): SdfShape` — TPMS block preset clipped to an explicit design space.
- `withinBox(shape: SdfShape, options: { size: Vec3; }): SdfShape` — Clip an SDF shape to a box-shaped design space.
- `noise(options?: NoiseOptions): SdfShape` — 3D Simplex noise field — produces organic, natural-looking displacements.
- `voronoi(options?: VoronoiOptions): SdfShape` — 3D Voronoi pattern — organic cellular structures like bone, coral, or soap bubbles.
- `honeycomb(options?: HoneycombOptions): SdfShape` — Honeycomb (hexagonal) lattice pattern. Intersect with your shape to apply.
- `waves(options?: WavesOptions): SdfShape` — Sinusoidal wave ridges — parallel ridges along an axis.
- `knurl(options?: KnurlOptions): SdfShape` — Knurl pattern — crossed helical grooves for grips and handles.
- `perforated(options?: PerforatedOptions): SdfShape` — Perforated plate pattern — regular array of cylindrical holes.
- `scales(options?: ScalesOptions): SdfShape` — Fish/dragon scale pattern — overlapping circular scales in hex-packed rows.
- `brick(options?: BrickOptions): SdfShape` — Brick/stone wall pattern — running bond with mortar grooves.
- `weave(options?: WeaveOptions): SdfShape` — Grid lattice pattern — two families of infinite slabs crossing at 90°.
- `basketWeave(options?: BasketWeaveOptions): SurfacePattern` — Basket weave surface pattern — threads with over-under crossings in UV space. Returns a SurfacePattern for use with `.surfaceDisplace()`.
- `pattern2d(): Pattern2DBuilder` — Create typed, composable 2D surface patterns for `.surfaceDisplace()`.
- `twist(shape: SdfShape, degreesPerUnit: number): SdfShape` — Twist an SDF shape around the Z axis.
- `bend(shape: SdfShape, radius: number): SdfShape` — Bend an SDF shape around the Z axis.
- `repeat(shape: SdfShape, spacing: Vec3, count?: Vec3): SdfShape` — Repeat an SDF shape in space.
- `circularArray(shape: SdfShape, count: number, offset?: number): SdfShape` — Arrange an SDF shape in a circular array around the Z axis with O(1) folded-domain evaluation.
- `SurfacePattern: typeof SurfacePattern` — A 2D surface pattern — a heightmap function for use with `.surfaceDisplace()`.
- `fromFunction(fn: SdfFunctionSource, options: SdfFunctionOptions): SdfShape` — Create a custom SDF from one expression; shader-safe expressions raymarch directly.
- `Sculpt: { sphere: (radius: number) => SdfShape; box: (x: number, y: number, z: number, options?: SculptBoxOptions) => SdfShape; cylinder: (height: number, radius: number) => SdfShape; disk: (radius: number, thickness?: number) => SdfShape; circle: (radius: number, thickness?: number) => SdfShape; capsule: (height: number, radius: number) => SdfShape; torus: (majorRadius: number, minorRadius: number) => SdfShape; cone: (height: number, radius: number) => SdfShape; tube: (points: SculptPointList, options?: SculptTubeOptions) => SdfShape; curve: (points: SculptPointList, options?: SculptTubeOptions) => SdfShape; path: (points: SculptPointList, options?: SculptTubeOptions) => SdfShape; blend: (first?: SculptBlendInput | SculptBlendOptions, optionsOrShape?: SculptBlendInput | SculptBlendOptions, ...rest: (SculptBlendInput | SculptBlendOptions)[]) => SdfShape; union: (first?: SculptBlendInput, ...rest: SculptBlendInput[]) => SdfShape; carve: (base: SdfShape, cutters: SculptBlendInput, options?: SculptBlendOptions) => SdfShape; keep: (first?: SculptBlendInput | SculptBlendOptions, optionsOrShape?: SculptBlendInput | SculptBlendOptions, ...rest: (SculptBlendInput | SculptBlendOptions)[]) => SdfShape; polish: (shape: SdfShape, input?: SculptPolishInput) => SdfShape; material: (input?: SculptPolishInput) => ShapeMaterialProps & { color?: string; }; look: (preset?: SculptLookPreset) => SceneOptions; knownMaterials: typeof knownSculptMaterialPresets; }` — Sculpt-like facade: friendly liquid-modeling verbs backed by the same SDF kernel.

### `Sculpt`

- `sphere(radius: number): SdfShape` — Create a liquid SDF sphere centered at the origin.
- `box(x: number, y: number, z: number, options?: SculptBoxOptions): SdfShape` — Create a liquid SDF box; pass `{ radius }` for a rounded box.
- `cylinder(height: number, radius: number): SdfShape` — Create a liquid SDF cylinder centered at the origin, axis along Z.
- `disk(radius: number, thickness?: number): SdfShape` — Create a thin circular disk centered at the origin, axis along Z. Useful as a circular cutter or insert.
- `circle(radius: number, thickness?: number): SdfShape` — Alias for `Sculpt.disk()`.
- `capsule(height: number, radius: number): SdfShape` — Create a liquid SDF capsule centered at the origin, axis along Z.
- `torus(majorRadius: number, minorRadius: number): SdfShape` — Create a liquid SDF torus lying in the XY plane.
- `cone(height: number, radius: number): SdfShape` — Create a liquid SDF cone.
- `tube(points: SculptPointList, options?: SculptTubeOptions): SdfShape` — Create a smooth tube through a list of 3D points.
- `curve(points: SculptPointList, options?: SculptTubeOptions): SdfShape` — Create a smooth variable-thickness sweep through 3D control points.
- `path(points: SculptPointList, options?: SculptTubeOptions): SdfShape` — Alias for `Sculpt.tube()`; points may use [x, y, z, radius] for variable thickness.
- `blend(first?: SculptBlendArg, optionsOrShape?: SculptBlendArg, ...rest: SculptBlendArg[]): SdfShape` — Smoothly blend one or more SDF shapes into a continuous body.
- `union(first?: SculptBlendInput, ...rest: SculptBlendInput[]): SdfShape` — Sharply union one or more SDF shapes.
- `carve(base: SdfShape, cutters: SculptBlendInput, options?: SculptBlendOptions): SdfShape` — Smoothly subtract one or more cutter shapes from a base shape.
- `keep(first?: SculptBlendArg, optionsOrShape?: SculptBlendArg, ...rest: SculptBlendArg[]): SdfShape` — Smoothly intersect one or more SDF shapes.
- `polish(shape: SdfShape, input?: SculptPolishInput): SdfShape` — Apply a Sculpt material preset or direct material properties.
- `material(input?: SculptPolishInput): ShapeMaterialProps & { color?: string; }` — Resolve a Sculpt material preset to ForgeCAD material properties.
- `look(preset?: SculptLookPreset): SceneOptions` — Return a polished scene preset tuned for liquid SDF preview.
- `knownMaterials(): SculptMaterialPreset[]` — List the built-in Sculpt material preset names.
