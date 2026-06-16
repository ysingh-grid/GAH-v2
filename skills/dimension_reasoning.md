# Skill: Dimension Reasoning

This guide details how to resolve relative offsets, clearances, coordinate locations, and bounding dimensions of shapes to generate valid CAD code.

## Critical Geometry Math Rules

1. **Center Points & Alignment**:
   - CadQuery primitives (like `box`, `cylinder`) are centered at the origin of their current workplane by default.
   - If a cylinder of height `H` is extruded or placed, its Z-bounds are from `-H/2` to `+H/2`.
   - If you want a cylinder to sit on top of a base flange of height `B` (which goes from `-B/2` to `+B/2`), the center of the cylinder must be placed at `Z = B/2 + H/2`.
   - **Crucial Rule**: Always track the half-heights and half-lengths to align faces flush.

2. **Interferences & Fits**:
   - **Holes/Pockets**: Must cut through the boundaries completely. To prevent floating point roundoff errors resulting in zero-thickness skins (non-manifold errors), extend the length/height of subtraction primitives slightly beyond the target face (e.g. make a through-hole cylinder height `H + 2` and offset its position by `1mm` outward).
   - **Clearance Fit**: If a shaft of diameter `D` fits into a hole, the hole diameter should be `D + clearance` (e.g. `0.2mm` or `0.5mm` clearance).

3. **Deriving Dependent Parameters**:
   - Volume estimates: `Volume_box = L * W * H`, `Volume_cylinder = pi * R^2 * H`, `Volume_cone = (1/3) * pi * R^2 * H`.
   - Use these simple formulas to predict and verify final shape volume.
