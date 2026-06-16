# Skill: Intent Extraction

This guide details how to extract engineering requirements, constraints, and dimensions from a user's free-form prompt.

## Intent Extraction Checklist

1. **Primary Object Identification**: What is the target component? (e.g., bracket, gear, cone, flange, adapter).
2. **Dimension Classification**:
   - **Explicit Dimensions**: Stated directly in the prompt (e.g., "height 45mm", "base diameter 30mm").
   - **Implicit Dimensions**: Standard scale or proportion constraints (e.g., "standard M6 bolt hole" -> 6.6mm diameter hole clearance).
   - **Variables/Parameters**: Named parameters that can change.
3. **Physical Constraints & Tolerances**:
   - Fit requirements (clearance, press-fit, sliding).
   - Alignment rules (centered, flush, offset).
   - Material constraints (e.g. wall thickness, minimum thickness).
4. **Target Functions**:
   - Holes for mounting.
   - Chamfers/Fillets for stress relief or handling.
   - Pockets/Shells for weight reduction.

## Output Format

The extracted intent should be structured in JSON for subsequent stages:

```json
{
  "target_object": "cone",
  "dimensions": {
    "base_diameter": {
      "value": 30.0,
      "unit": "mm",
      "type": "explicit"
    },
    "height": {
      "value": 45.0,
      "unit": "mm",
      "type": "explicit"
    }
  },
  "constraints": {
    "watertight": true,
    "top_sharp": true
  }
}
```
Use this structure to formulate the base constraints for the primitive planning phase.
