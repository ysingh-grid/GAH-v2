# Skill: Primitive Planning

This guide describes how to convert a decomposed geometry plan into a structured JSON representation (`PrimitivePlan`) using the primitives defined in the primitive library.

## Primitive Selection Rules

- Always match the physical description to the closest matching schema in `primitives/library.json` (e.g. use `cone` for cones, `cylinder` for shafts, `box` for blocks).
- If a shape does not map perfectly to a single primitive, use a combination of primitives and CSG actions.
- Ensure all parameters passed match the type (float/int) and description in the library schema.

## CSG Operation Syntax in Plan

Every step in a primitive plan must have:
- `id`: A unique name/identifier for the primitive.
- `primitive`: The name of the primitive from `library.json`.
- `operation`: One of `base`, `union` (add), or `cut` (subtract).
- `parameters`: Key-value pairs of parameters that match the primitive's schema.
- `position`: Coordinates `[x, y, z]` where the primitive should be centered/placed.
- `orientation`: Rotation angles `[rx, ry, rz]` in degrees.

## Plan JSON Example (Cone with Base Cylindrical Flange)

```json
[
  {
    "id": "base_flange",
    "primitive": "cylinder",
    "operation": "base",
    "parameters": {
      "radius": 15.0,
      "height": 5.0
    },
    "position": [0.0, 0.0, 0.0],
    "orientation": [0.0, 0.0, 0.0]
  },
  {
    "id": "cone_body",
    "primitive": "cone",
    "operation": "union",
    "parameters": {
      "base_diameter": 30.0,
      "top_diameter": 0.0,
      "height": 40.0
    },
    "position": [0.0, 0.0, 5.0],
    "orientation": [0.0, 0.0, 0.0]
  }
]
```
Ensure that position offsets correctly stack primitives to avoid overlaps or gaps!
