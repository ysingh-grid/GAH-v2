---
name: intent_extraction
version: "1.0"
purpose: >
  Parse a user's free-form CAD prompt into a structured JSON intent object
  containing the target object, explicit/implicit dimensions, and constraints.
used_by:
  - planner (intent step of every plan)
inputs:
  - user_prompt: "Raw natural-language design request string"
  - primitives_list: "context[\"available_primitives\"] — supported primitive keys"
outputs:
  - target_object: "Closest matching primitive name"
  - dimensions: "Dict of param → {value, unit, type}"
  - constraints: "Dict of geometric/functional constraints"
tags: [planning, intent, parsing, phase1]
token_budget: low   # ~300 tokens body — load always
---

# Skill: Intent Extraction

Extract engineering requirements, constraints, and dimensions from a user's
free-form prompt. This is **Phase 1 / Step 1** of the RLM pipeline.

## Intent Extraction Checklist

1. **Primary Object Identification** — What is the target component?
   (e.g., bracket, gear, cone, flange, adapter, hollow cylinder)

2. **Dimension Classification**
   - **Explicit**: Stated directly — e.g., "height 45mm", "base diameter 30mm"
   - **Implicit**: Standard scale constraints — e.g., "M6 bolt hole" → 6.6mm clearance diameter
   - **Variables**: Named parameters that may change (parametric design)

3. **Physical Constraints & Tolerances**
   - Fit requirements: clearance, press-fit, sliding
   - Alignment rules: centered, flush, offset
   - Material constraints: wall thickness, minimum thickness

4. **Functional Features**
   - Holes for mounting
   - Chamfers/Fillets for stress relief or handling
   - Pockets/Shells for weight reduction

## Output Format

Return **only** a valid JSON object:

```json
{
  "target_object": "cone",
  "dimensions": {
    "base_diameter": { "value": 30.0, "unit": "mm", "type": "explicit" },
    "height":        { "value": 45.0, "unit": "mm", "type": "explicit" }
  },
  "constraints": {
    "watertight": true,
    "top_sharp": true
  }
}
```

> **Rule**: `target_object` must be one of the supported primitive names passed in
> `primitives_list`. Use your best judgment to match the user's description.
