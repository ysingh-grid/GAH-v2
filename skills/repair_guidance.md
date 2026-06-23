---
name: repair_guidance
version: "2.0"
purpose: >
  Help the Repair Sub-Agent identify the root cause of a compilation/execution failure
  and apply the minimal targeted fix to the PrimitivePlan JSON representation.
used_by:
  - repair_sub_agent (W·01 inner repair loop, max 3 attempts)
inputs:
  - broken_plan: "The PrimitivePlan JSON representation that failed compilation/execution"
  - error_message: "The error message or traceback from the CAD execution"
outputs:
  - fixed_plan: "A revised/corrected PrimitivePlan JSON representation matching the schema"
tags: [repair, debugging, primitive-plan, json, errors, W01, inner-loop]
token_budget: medium  # ~600 tokens — load only when repair is triggered
sub_agent_contract: >
  Return ONLY the corrected PrimitivePlan JSON representation.
  No markdown fences, no explanations.
  Must conform exactly to the PrimitivePlan schema (a dictionary with a "plan" key containing list of steps, or a list of steps).
---

# Skill: Repair Guidance (Inner Loop)

Fix PrimitivePlan errors that cause compilation or execution failures. This is used by the **Repair Sub-Agent** inside the **W·01 inner repair loop** (max 3 attempts).

> **Contract**: Return ONLY the corrected PrimitivePlan JSON. No markdown, no prose.
> The output MUST be a valid JSON representation matching the `PrimitivePlan` schema.

---

## Common PrimitivePlan Failures & Targeted Fixes

### 1. Schema Validation Failures (Invalid Keys or Types)
If the compiler/schema validator raises errors like:
* `"Unexpected parameter 'width' is not allowed for primitive type 'cylinder'"`
* `"Parameter 'radius' for step 'mount_hole' must be of type float, got value 'ten'"`
* `"Missing required parameter 'height' for primitive type 'box'"`

* **Fix**: 
  - Cross-reference parameters with the allowed parameters for that primitive.
  - Cylinder parameters: `radius`, `height`.
  - Box parameters: `length`, `width`, `height`.
  - Sphere parameters: `radius`.
  - Ensure all numeric values are standard JSON numbers (e.g., `10.0` or `5`), not strings (e.g., `"10.0"`).

### 2. CSG Boolean Operation & Non-Manifold Failures
If execution fails due to CAD kernel errors like:
* `Standard_ConstructionError: BRep_API: command not done`
* Non-manifold topology or disjoint shape errors.

* **Fix**:
  - **Union Overlaps**: Ensure consecutive features to be unioned overlap by at least `0.1mm` to avoid co-planar alignment issues or tiny floating gaps. Adjust the `position` coordinate along the joining axis.
  - **Cut Clearances**: Ensure cutters (cut operations) fully penetrate the target body. A cutting tool must be slightly larger than the material it cuts (e.g., height is `thickness + 2.0` mm, offset by `1.0` mm outward along the cutting direction).
  - **First Step**: Ensure the very first step in the plan has `operation: "base"`. Subsequent steps must have `operation: "union"` or `operation: "cut"`.

### 3. Invalid Orientation / Rotation Angles
* **Fix**:
  - The `orientation` field must contain exactly three float values `[rx, ry, rz]` representing rotation angles in degrees around the X, Y, and Z axes.
  - Default orientation stands along the Z-axis.

---

## Repair Workflow

1. Read `error_message` / traceback and locate the failing step `id` or primitive.
2. Cross-reference the `broken_plan` with the primitive definitions.
3. Apply the **targeted** parameter or position fix directly to the JSON structure.
4. Ensure the returned output is a clean JSON representation of the `PrimitivePlan` (containing the `"plan"` list).
5. Return ONLY the JSON object. Do not wrap in markdown code blocks.
