---
name: repair_guidance
version: "2.0"
purpose: >
  Help identify the root cause of a CadQuery compilation or execution failure
  and apply the minimal targeted fix to the PrimitivePlan JSON structure.
used_by:
  - replanner (re-entered during the inner repair loop, shared cap of 5 attempts)
inputs:
  - failure_detail: "The compiler or execution traceback / error message"
  - primitive_plan: "Current PrimitivePlan dict"
outputs:
  - PrimitivePlan: "Corrected JSON plan matching the schema"
tags: [repair, debugging, JSON, schema, inner-loop]
token_budget: medium  # ~600 tokens
---

# Skill: Repair Guidance (Inner Loop)

Fix errors that cause the CadQuery compiler or execution kernel to crash. Since the pipeline compiles your JSON plan into Python code deterministically, you must fix the **JSON PrimitivePlan parameters**, not Python syntax.

> **Contract**: Return a corrected JSON `PrimitivePlan` directly inside your `FINAL` block.

---

## 🛠️ Common Errors & Targeted JSON Fixes

### Error 1 — Fillet/chamfer radius too large (`BRep_API: command not done` or Standard_ConstructionError inside `.fillet()`)
The fillet or chamfer radius in your `FinishStep` exceeds the physical limits of the adjacent face.
- **Rule**: A fillet/chamfer radius (`value` parameter) MUST be strictly less than half of the smallest dimension of the face or edge it is applied to.
- **How to fix in JSON**: Locate the `FinishStep` with `"op": "fillet"` or `"op": "chamfer"`. Reduce its `"value"` to a smaller, safer number (e.g., reduce a `3.0` fillet to `1.0` or `1.5`).

### Error 2 — Non-Manifold / Co-planar Faces / Disjoint Unions (`BRep_API: command not done`)
Occurs when two unioned bodies just barely touch (tangent faces/edges) or when a cutter (operation: `cut`) has faces exactly co-planar with the base shape, producing infinite infinitesimals in the geometry kernel.
- **How to fix cuts**: Extend the size of the cutting primitive by at least `2.0mm` in the cutting direction, and adjust its position so it starts `1.0mm` outside the base shape and ends `1.0mm` outside the other side. This ensures a clean fully penetrating cut.
- **How to fix unions**: Do not place unioned shapes exactly tangent. Ensure they overlap by shifting the position of the joining primitive slightly (overlap of `0.5mm` to `1.0mm` into the base body).

### Error 3 — Empty Selector / Element Missing (`IndexError` during selection)
An edge or face selector (like `">Z"`, `"|Z"`) was requested but couldn't be resolved on the compiled solid because the solid's topology changed (e.g., a cut removed the face, or a rotation shifted its axis alignment).
- **How to fix in JSON**: If you rotated the solid, remember the faces rotate too. Check if `"face": ">Z"` in your `FinishStep` is still the correct target axis. Consider using broader selectors like `"#Z"` (all faces with normals parallel to Z) or target a different adjacent face.

### Error 4 — Multiple Base Steps
The parser automatically coerces extra `base` steps to `union`, but it is best to fix this in your plan.
- **How to fix in JSON**: Ensure exactly the first step in your `"steps"` list has `"operation": "base"`. Every other step — even for separate disjoint bodies — must have `"operation": "union"`, `"cut"`, or `"intersect"`.

---

## Repair Workflow

1. Read the `Failure detail` traceback or message.
2. Locate the specific step (by `"id"`) that caused the error.
3. Apply the targeted parameter/position adjustment in the JSON plan. Do NOT rewrite the entire plan from scratch; keep unaffected steps identical.
4. Verify that the geometry has overlapping unions and clean penetrating cuts.
5. Return the updated JSON `PrimitivePlan`.
