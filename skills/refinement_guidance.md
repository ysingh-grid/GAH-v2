---
name: refinement_guidance
version: "2.0"
purpose: >
  Help the Refinement Sub-Agent adjust primitive parameters and positioning
  coordinates in the PrimitivePlan JSON representation based on visual/geometric
  feedback from the verifier, without rewriting the whole design.
used_by:
  - refine_sub_agent (W·05 outer refinement loop, max 5 attempts)
inputs:
  - current_plan: "The PrimitivePlan JSON representation that passed compilation/execution but has verification errors"
  - verdict: "Verifier output dict with passed, score, issues, feedback, and failure_category"
  - attempt: "Current refinement attempt number (1–5)"
outputs:
  - refined_plan: "Updated PrimitivePlan JSON representation with corrected parameters/positioning"
tags: [refinement, feedback, geometry, W05, outer-loop, json]
token_budget: low   # ~500 tokens — load only when refinement is triggered
sub_agent_contract: >
  Return ONLY the corrected PrimitivePlan JSON representation.
  No markdown fences, no explanations.
  Must conform exactly to the PrimitivePlan schema (a dictionary with a "plan" key containing list of steps, or a list of steps).
---

# Skill: Refinement Guidance (Outer Loop)

Adjust geometry parameters and positions based on verifier feedback. Used by the **Refinement Sub-Agent** in the **W·05 outer refinement loop** (max 5 attempts).

> **Contract**: Return ONLY the corrected PrimitivePlan JSON. No markdown, no prose.
> The output MUST be a valid JSON representation matching the `PrimitivePlan` schema.

---

## Feedback → PrimitivePlan Fix Mapping

### 1. Dimension Mismatch (e.g., Size / Radius / Diameter)
**Example feedback**: *"The cone base is 15mm instead of 30mm."*

* **Adjustment Rule**:
  - Check the primitive's parameter schema. Many primitives require **radius** instead of **diameter**.
  - If the prompt specifies "base diameter 30mm" and you put `"radius": 30.0` or `"radius": 15.0`, cross-reference with how it translates in CAD.
  - Scale/adjust the dimension parameters directly in the `"parameters"` dictionary of the relevant step.
  - Example change:
    ```json
    // Before
    "parameters": { "radius": 30.0 }
    // After
    "parameters": { "radius": 15.0 }
    ```

### 2. Positioning Offsets & Alignment (X, Y, Z Coordinate Adjustments)
**Example feedback**: *"The cylinder top cap sits 5mm too low and intersects the base."*

* **Adjustment Rule**:
  - Examine the `position` array `[x, y, z]` of the misplaced primitive.
  - To shift a shape up or down along the Z-axis, modify `position[2]`.
  - Re-calculate Z coordinate using the **half-height rule**:
    $$\text{center}_Z = \text{base\_center}_Z + \frac{\text{base\_height}}{2} + \frac{\text{feature\_height}}{2}$$
  - For example, if a base cylinder has `height: 10` (centered at `[0, 0, 5]`, so base top is at `Z=10`), and a feature cylinder has `height: 30`, its center Z should be $10 + 15 = 25$. If it was set to `20`, shift it to `25` by editing the `position` array: `[0.0, 0.0, 25.0]`.

### 3. Missing Features
**Example feedback**: *"There are no mount holes."*

* **Adjustment Rule**:
  - Verify if a primitive step with `"operation": "cut"` exists in the plan.
  - Ensure the cutter's dimensions actually overlap with the main body.
  - Increase the cutter's `height` or adjust its `position` so it fully passes through the parts it's supposed to cut.

### 4. Orientation Issues
**Example feedback**: *"The cylinder is lying flat along X instead of standing vertically."*

* **Adjustment Rule**:
  - Modify the `orientation` array `[rx, ry, rz]` for the specific primitive.
  - Primitives usually align along the Z axis by default. To orient along X or Y, specify the correct rotation in degrees (e.g., `[90.0, 0.0, 0.0]`).

---

## Refinement Checklist

1. Review the verifier's `verdict` (especially `feedback` and `failure_category`).
2. Identify the incorrect step `id` in the `current_plan`.
3. Make localized edits to `parameters`, `position`, or `orientation` in the JSON. Do not reconstruct the plan from scratch unless the structure is fundamentally wrong.
4. Ensure the modified structure remains valid under the `PrimitivePlan` schema.
5. Return ONLY the final JSON object. Do not wrap in markdown code blocks.
