---
name: refinement_guidance
version: "1.0"
purpose: >
  Help the Refinement Sub-Agent adjust primitive parameters and positioning
  coordinates based on visual/geometric feedback from the verifier, without
  rewriting the whole design.
used_by:
  - refine_sub_agent (W·05 outer refinement loop, max 5 attempts)
inputs:
  - current_code: "The CadQuery Python code that passed compilation"
  - verdict: "Verifier output dict with passed/score/issues/feedback"
  - primitive_plan: "PrimitivePlan dict with resolved parameters"
  - attempt: "Current refinement attempt number (1–5)"
outputs:
  - refined_code: "Updated Python code string assigning final solid to `result`"
tags: [refinement, feedback, geometry, W05, outer-loop]
token_budget: low   # ~500 tokens — load only when refinement is triggered
sub_agent_contract: >
  Return ONLY the corrected Python code string.
  No markdown fences, no explanations.
  Final solid MUST be assigned to `result`.
---

# Skill: Refinement Guidance (Outer Loop)

Adjust geometry based on verifier feedback. Used by the **Refinement Sub-Agent**
in the **W·05 outer refinement loop** (max 5 attempts).

> **Contract**: Return ONLY the corrected Python code. No markdown, no prose.
> Final solid MUST be assigned to `result`.

---

## Feedback → Fix Mapping

### 1. Size Mismatch
**Example feedback**: *"The cone base is 15mm instead of 30mm."*

- Check: Did you pass **radius** where **diameter** was required (or vice versa)?
  - CadQuery's `makeCone(r1, r2, h)` takes **radius**, not diameter.
  - If the prompt says "base diameter 30mm" → pass `r1 = 30.0 / 2.0 = 15.0`.
- Scale the affected parameter accordingly.

### 2. Position Offset / Misalignment
**Example feedback**: *"The cylinder top cap sits 5mm too low and intersects the base."*

- Re-verify Z coordinate using the **half-height rule**:
  ```
  shaft_center_z = base_height/2 + shaft_height/2
  ```
  - If `base_height=10`, `shaft_height=30` → `shaft_center_z = 5 + 15 = 20`
  - If you used `z=15`, it intersects by `5mm`. Fix: set to `20`.

### 3. Missing Features
**Example feedback**: *"There are no mount holes."*

- Check: Did you define the hole cutter but forget the `.cut()` call?
- Check: Is the cutter cylinder tall enough to fully penetrate the body?
  - Remember: cutter must be `H + 2mm` tall, offset by `1mm` outward.

### 4. Orientation Errors
**Example feedback**: *"The cylinder is lying flat along X instead of standing vertically."*

- CadQuery cylinders default to standing along **Z axis**.
- To rotate: `.rotate((0,0,0), (1,0,0), 90)` lays it along X.
- To stand along Y: `.rotate((0,0,0), (1,0,0), 90).rotate((0,0,0), (0,0,1), 90)`

### 5. Score < 60 — General Checklist

1. Re-read the original prompt for missed constraints.
2. Check all dimensions against the `primitive_plan.parameters` — did any
   get dropped or scaled incorrectly?
3. Verify CSG operations are in the correct order (base → union → cut → finish).
4. Check edge finishing (fillets/chamfers) aren't too large for the geometry.
