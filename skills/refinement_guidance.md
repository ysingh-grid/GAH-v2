---
name: refinement_guidance
version: "2.0"
purpose: >
  Adjust primitive parameters and positioning coordinates in the PrimitivePlan
  JSON based on visual or geometric feedback from the verifier.
used_by:
  - replanner (re-entered during the outer refinement loop, cap of 3 attempts)
inputs:
  - verifier_feedback: "Verifier output dict with passed/score/issues/feedback"
  - primitive_plan: "Current PrimitivePlan dict"
outputs:
  - PrimitivePlan: "Corrected JSON plan matching the schema"
tags: [refinement, feedback, geometry, JSON, outer-loop]
token_budget: low   # ~500 tokens
---

# Skill: Refinement Guidance (Outer Loop)

Adjust geometry based on verifier feedback. Used during the **outer refinement loop** (cap of 3 attempts).

> **Contract**: Return a corrected JSON `PrimitivePlan` directly inside your `FINAL` block. Do NOT write Python code.

---

## 📐 Feedback → JSON Parameter Fixes

### 1. Dimension Mismatches
**Example feedback**: *"The cone base is 15mm instead of 30mm."*
- **Verify Radii vs Diameters**: Many primitives take radii, but natural language prompts specify diameters (or vice versa).
  - Check the primitive's schema by reference (using `lookup_primitive`).
  - If the prompt specifies "diameter 30mm" and the parameter is `"radius"` (like in cylinders/spheres), you must divide by 2: set the parameter `"radius": 15.0`.
  - If the parameter expects `"diameter"` (like in cone's `"base_diameter"`), set it directly to `30.0`.

### 2. Position Offset / Misalignment
**Example feedback**: *"The cylinder top cap sits 5mm too low and intersects the base."*
- **Half-Height Rule**: When stacking bodies along an axis, compute positions relative to body centerlines.
  - If placing a cylinder of `height=30` on top of a box of `height=10` centered at Z=0:
    - Box occupies Z from `-5.0` to `5.0`.
    - Cylinder centerline must sit at `box_top_Z + cylinder_half_height = 5.0 + 15.0 = 20.0`.
    - Set `"position": [0.0, 0.0, 20.0]` for the cylinder.
  - Correct any incorrect position coordinate in the `"position"` array of the target step.

### 3. Missing Features
**Example feedback**: *"There are no mount holes."*
- Check: Did you define the `cut` primitive or `hole` finish step?
  - Verify that the step's `"operation"` is set to `"cut"`. If it's `"union"`, it adds material instead of subtracting.
  - Ensure that cutting primitives fully penetrate. A hole cutter should be slightly longer than the body thickness and offset so it clears both faces.

### 4. Orientation Errors
**Example feedback**: *"The cylinder is lying flat along X instead of standing vertically."*
- Locate the step's `"orientation"` parameter (expressed as degrees of rotation about `[X, Y, Z]`).
  - To rotate a Z-aligned primitive (like a cylinder) to lie flat along the X axis, set `"orientation": [0.0, 90.0, 0.0]`.
  - Correct the rotation coordinates to align with the verifier's expectations.

---

## Refinement Workflow

1. Read the `Verifier feedback` carefully to identify which physical dimensions or alignments failed.
2. Locate the corresponding PrimitiveStep or FinishStep in your plan.
3. Apply the minimal necessary adjustments to `"parameters"`, `"position"`, or `"orientation"`. Keep every other step byte-for-byte identical.
4. Verify the stack offsets using the centerline rules.
5. Return the updated JSON `PrimitivePlan`.
