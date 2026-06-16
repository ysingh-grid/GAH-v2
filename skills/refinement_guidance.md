# Skill: Refinement Guidance (Outer Loop)

This guide provides strategies for the Refinement Sub-Agent to adjust primitive arguments and positioning coordinates based on feedback from the visual and geometric verifier.

## Adjusting Parameters Based on Feedback

1. **Size Mismatch**:
   - Feedback: "The cone base is too small; it looks like 15mm instead of 30mm."
   - Check: Did you pass the radius instead of diameter or vice versa? CadQuery's `.cone()` takes `radius1` and `radius2`. If the prompt asks for a "base diameter 30mm", you must pass `30.0 / 2.0 = 15.0` as the base radius.
   - Adjust the plan parameters to scale correctly.

2. **Position Offset / Misalignment**:
   - Feedback: "The cylinder top cap sits 5mm too low and intersects the base."
   - Check: Re-verify Z coordinate calculations. Remember that `cylinder` is centered at its mid-height. If the base plate height is `10` and the cylinder height is `30`, sitting it directly on top of the base requires `Z = 10/2 + 30/2 = 5 + 15 = 20`. If it sits at `Z = 15`, it will intersect by `5mm`.
   - Update coordinates in the plan.

3. **Missing Features**:
   - Feedback: "There are no mount holes present."
   - Check: Did you define the hole primitive but forget to perform the `.cut()` operation in the compiled script, or was the cutter size too small to penetrate?
   - Add/verify the CSG subtraction steps.

4. **Orientation Errors**:
   - Feedback: "The cylinder is lying flat along X instead of standing vertically along Z."
   - Check: Check the rotation. By default, CadQuery cylinders stand along the Z axis. If you need to rotate them, use `.rotate((0,0,0), (1,0,0), 90)` or create a workplane on a different face (e.g., `.workplane("YZ")`).
