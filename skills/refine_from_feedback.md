---
name: refine_from_feedback
version: "2.0"
purpose: >
  Interpret visual or geometric feedback about a CAD model and make targeted
  parameter adjustments to fix the reported issue — without rewriting the entire
  design from scratch. Self-contained feedback-to-fix mapping portable to any
  parametric CAD system.
inputs:
  - feedback: Text description of what's wrong with the current design
  - current_params: The parameter values used in the current attempt
  - current_positions: The position vectors used in the current attempt
outputs:
  - adjusted_params: Corrected parameter values
  - adjusted_positions: Corrected position vectors
  - fix_description: What was changed and why
tags: [refinement, feedback, adjustment, geometry, portable]
token_budget: low
---

# Skill: Refine From Feedback

When a verifier or user reports that the geometry is wrong, don't start over.
Match the feedback to a known issue type, change only the broken parameter,
and verify your fix with the math from `compute_dimensions`.

---

## Feedback → Fix Mapping

### Issue 1 — Size Mismatch (dimensions wrong)

**Example feedback:**
- "The cone base is 15mm instead of 30mm."
- "The block is 50% too small."
- "The hole diameter is too large."

**Diagnosis:**
Check whether you passed **radius** where **diameter** was required (or vice versa).
This is the most common cause of exact 2× or 0.5× errors.

**Fix:**
- Know your geometry kernel's parameter conventions:
  - CadQuery `makeCone(r1, r2, h)` takes **radius**, not diameter.
  - CadQuery `.cylinder(height, radius)` takes **radius**.
  - If the prompt says "base diameter 30mm" → `r1 = 30.0 / 2.0 = 15.0`.
  - If the prompt says "base radius 15mm" → `r1 = 15.0` directly.
- Scale the affected parameter: if it's exactly half or double what it should
  be, it's a radius-vs-diameter confusion.

**Check your work:**
- Look at the original request text. Does it say "diameter" or "radius"?
- Your primitive schema may use different terms. Map:
  - Request says "diameter X" → schema says "radius" → divide by 2.
  - Request says "radius Y" → schema says "radius" → use directly.

---

### Issue 2 — Position Offset / Misalignment

**Example feedback:**
- "The cylinder sits 5mm too low and intersects the base."
- "The flange is offset to the right by 3mm."
- "The top face is not flush with the shaft."

**Diagnosis:**
Re-verify the Z-coordinate using the **half-height stacking rule** from
`compute_dimensions`. This is almost always a centering convention error.

**Fix — Z stacking check:**
```
For a CENTERED cylinder on top of a CENTERED body:
  body_top_z = body.position.z + body.height / 2
  shaft_center_z = body_top_z + shaft_height / 2

Example:
  Base: position.z = 0, height = 10 → body_top_z = 0 + 5 = 5
  Shaft: height = 30 → shaft_center_z = 5 + 15 = 20

  If you used z = 15: the shaft intersects by 5mm. Fix: set position.z = 20.
```

**Fix — XY offset check:**
- Centered features should be at (0, 0) unless intentionally offset.
- Patterned features (polar arrays): compute from the pattern center, not the
  global origin.
- `polar pattern at radius R, angle θ`: `x = R × cos(θ)`, `y = R × sin(θ)`.

---

### Issue 3 — Missing Features

**Example feedback:**
- "There are no mount holes."
- "The chamfer is missing from the top edge."
- "The shell/hollowing wasn't applied."

**Diagnosis — check three things:**
1. Did you define the feature but forget the boolean operation?
   - Cutter cylinder exists → but no `.cut(cutter)` call.
   - Fillet radius defined → but no `.fillet()` call in the code.
2. Is the feature's cutter positioned correctly to intersect the body?
   - A hole cutter at z=0 when the body is at z=50 won't cut anything.
3. Is the feature applied in the correct ORDER?
   - Fillets/chamfers/shells must come AFTER all CSG operations.
   - A fillet applied before a cut may be removed by the cut.

**Fix:**
- Add the missing `.cut()`, `.union()`, `.fillet()`, etc. call.
- If the cutter exists but at the wrong position, adjust its position and height:
  ```
  hole_center_z = body_top_z / 2  (centered in the body)
  hole_height = body_total_height + 2  (pierces through)
  ```

---

### Issue 4 — Orientation Errors

**Example feedback:**
- "The cylinder is lying flat along X instead of standing vertically."
- "The part is rotated 90 degrees from what was requested."
- "The holes are on the wrong face."

**Diagnosis:**
Default orientations vary by cad kernel:
- CadQuery cylinders default to standing along the **Z axis**.
- CadQuery boxes default to edges aligned with X, Y, Z axes.

**Fix — rotation:**
```python
# To rotate a shape 90° around X (so it lies along Y):
shape.rotate((0,0,0), (1,0,0), 90)

# To stand along Y:
shape.rotate((0,0,0), (1,0,0), 90).rotate((0,0,0), (0,0,1), 90)
```

Rotation applies around the specified axis through the origin point.

**Fix — hole placement on a different face:**
- CadQuery face selectors: `">Z"` = top, `"<Z"` = bottom, `">X"` = right side,
  `">Y"` = front.
- If holes should be on the top face, use `.faces(">Z").workplane()`.
- If on a side face, use the appropriate selector.

---

### Issue 5 — Low Quality Score (comprehensive check)

**Example feedback:** "The model scores 45/100." or "Multiple issues detected."

**Diagnosis checklist — go through in order:**

1. **Re-read the original request.** What constraints did you miss?
   - "A hollow cylinder" → did you apply shell?
   - "With rounded edges" → did you apply fillets?
   - "4 mounting holes" → are there exactly 4?

2. **Check all dimensions against the current parameters.**
   - Did any parameter get dropped during the conversion from plan to code?
   - Did any value get scaled incorrectly?
   - Are units consistent (all in mm)?

3. **Verify the CSG operation order.**
   - base → union → cut → finish. This order is critical.
   - A cut before a union may punch through the wrong geometry.
   - A finish before a cut may get obliterated.

4. **Check edge finishing constraints.**
   - Fillets/chamfers: is the radius small enough for the adjacent geometry?
     (See Error 2 in `debug_cadquery` for the max fillet radius calculation.)
   - Shell: is the wall thickness > 0 and < the smallest dimension?

5. **Check for union overlap.**
   - Every unioned feature MUST overlap the body by ≥ 0.5mm.
   - Features touching only at a tangent face don't fuse.

---

## Refinement Discipline

1. **One fix at a time.** Don't change five parameters simultaneously — you
   won't know which one fixed the issue.

2. **Apply `compute_dimensions` math.** After adjusting a position or dimension,
   recalculate the stacking to make sure the fix doesn't create a new problem
   (e.g., fixing a Z offset but now causing a union overlap issue).

3. **If the feedback is vague** ("it doesn't look right"), ask for specifics:
   which dimension is wrong? which feature is missing? which face doesn't match?

4. **After changing a parameter, re-predict volume.** If the new predicted
   volume now aligns with what the verifier expects, your fix is likely correct.

5. **Track what you changed.** If the same feedback comes back after your fix,
   your diagnosis was wrong — re-read the feedback for a different clue.