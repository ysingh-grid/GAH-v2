# ForgeCAD Docs Index

Use this index to choose which ForgeCAD reference topic to query with host tools. Do not paste full docs into the prompt.

## Official Docs

| Topic | URL | Use When |
|---|---|---|
| `concepts` | `https://forgecad.io/docs/concepts` | Execution model, injected globals, valid return values, script structure. |
| `core` | `https://forgecad.io/docs/core` | 3D primitives, transforms, booleans, parameters, placement, edge operations. |
| `sketch` | `https://forgecad.io/docs/sketch` | 2D profiles, rectangles, circles, polygons, slots, sketch booleans, extrude. |
| `curves` | `https://forgecad.io/docs/curves` | Loft, sweep, splines, curves, smooth surface workflows. |
| `assembly` | `https://forgecad.io/docs/assembly` | Multi-part models, joints, connectors, mating, mechanisms. |
| `output` | `https://forgecad.io/docs/output` | Export, BOM, dimensions, output metadata. |
| `lib` | `https://forgecad.io/docs/lib` | Fasteners, gears, bearings, hardware, reusable library parts. |
| `sheet-metal` | `https://forgecad.io/docs/sheet-metal` | Bends, flanges, panels, flat patterns, K-factor. |
| `viewport` | `https://forgecad.io/docs/viewport` | Viewer-only render settings, cut planes, labels, inspections. |
| `sdf` | `https://forgecad.io/docs/sdf` | Organic shapes, smooth implicit geometry, blobs, lattices, TPMS. |

## Lookup Workflow

1. Call `forgecad_doc_topics(prompt)` to select topics.
2. Call `forgecad_api_lookup(topic)` for each selected topic.
3. Call `forgecad_web_doc_lookup(topic)` only if local lookup is missing an API needed for generation or compile repair.
4. Generate direct `.forge.js` using only ForgeCAD APIs from the snippets.
