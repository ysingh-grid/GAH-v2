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

### Error 2 — An operation failed to build the solid (`BRep_API: command not done` / `StdFail_NotDone`, or a hard crash / return code -11)
The CAD kernel could not complete ONE operation. The `Failure detail` names the
ATTRIBUTED step ("failed at step 'X' (op: Y)") — fix THAT step, not the whole plan.
- **Verify before you commit.** Do NOT blind-`FINAL` a fix to a build failure:
  after changing the step, `preview_plan(plan)` and confirm `compiles`/`executes`
  are true and `num_components == 1` BEFORE `FINAL`.
- **If the SAME op keeps failing, change the CONSTRUCTION, not just its number.**
  A richer single primitive usually removes the failure entirely (see
  `primitive_planning`): a hollow vessel is `hollow_cylinder`/`revolve`, not a
  `shell` finish; a rounded box is `filleted_box`, not a whole-body `fillet`.
- **Read the CAUSE class in the failure detail** — do not always "extend overlap":
  - **multi-solid / severing cuts** → shallow grooves only; never cut the body into
    separate pieces (decorative Rubik-style lines must not sever material).
  - **multi-shell / enclosed void** → open the cavity to outside (cup cut with floor
    + open top, or shell open-face last). Never a sealed balloon. No separate cap body.
  - **shell-then-union** → illegal; hollow LAST or ONE `revolve` / `hollow_cylinder`.
  - **true touching unions only** → extend each union feature `0.5–1.0mm` into the body.
- **`cut` co-planar with a face** → extend the cutter ~`1mm` past each side so it
  penetrates cleanly (no zero-thickness slivers).

### Error 3 — Empty Selector / Element Missing (`IndexError` during selection)
An edge or face selector (like `">Z"`, `"|Z"`) was requested but couldn't be resolved on the compiled solid because the solid's topology changed (e.g., a cut removed the face, or a rotation shifted its axis alignment).
- **How to fix in JSON**: If you rotated the solid, remember the faces rotate too. Check if `"face": ">Z"` in your `FinishStep` is still the correct target axis. Consider using broader selectors like `"#Z"` (all faces with normals parallel to Z) or target a different adjacent face.

### Error 4 — Multiple Base Steps
The parser automatically coerces extra `base` steps to `union`, but it is best to fix this in your plan.
- **How to fix in JSON**: Ensure exactly the first step in your `"steps"` list has `"operation": "base"`. Every other step must have `"operation": "union"`, `"cut"`, or `"intersect"`, and each `union` feature must overlap the body it joins so the result stays ONE connected watertight solid.

---

## Repair Workflow

1. Read the `Failure detail` traceback or message.
2. Locate the specific step (by `"id"`) that caused the error.
3. Apply the targeted parameter/position adjustment in the JSON plan. Do NOT rewrite the entire plan from scratch; keep unaffected steps identical.
4. Verify that the geometry has overlapping unions and clean penetrating cuts.
5. Return the updated JSON `PrimitivePlan`.
