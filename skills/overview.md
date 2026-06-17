---
name: overview
version: "1.0"
purpose: >
  Master index of all skills in the CAD RLM system. Describes the multi-phase
  pipeline, which skill is used at each phase, and its token budget.
used_by:
  - planning_worker (boot — fast scan to select which skills to load)
  - all agents (reference)
inputs: []
outputs:
  - skill_index: "Name → phase mapping for skill selection"
tags: [index, overview, pipeline, meta]
token_budget: minimal  # Always load — it's the cheapest skill
---

# CAD RLM — Skills Overview

All skills live in `skills/*.md` with **YAML frontmatter metadata**.
The `read_skill_meta()` function reads only the metadata (< 1ms, zero LLM tokens).
The `read_skill()` function reads the full body for injection into prompts.

---

## Skill Registry

| Skill | Phase | Used By | Token Budget |
|---|---|---|---|
| `intent_extraction` | Phase 1 — Step 1 | planning_worker | low |
| `part_decomposition` | Phase 1 — Step 1.5 | planning_worker (complex) | low |
| `primitive_planning` | Phase 1 — Steps 2–3 | planning_worker | low |
| `dimension_reasoning` | Phase 1 — Steps 2–3 | planning_worker | low |
| `cadquery_cookbook` | Phase 2 — Code Gen | planning_worker, repair, refine | medium |
| `repair_guidance` | Phase 3 — Inner Loop | repair_sub_agent (max 3) | medium |
| `verification_planning` | Phase 3–4 | planning_worker, verifier | low |
| `refinement_guidance` | Phase 5 — Outer Loop | refine_sub_agent (max 5) | low |

---

## Pipeline Map

```
Phase 1: Planning (Root RLM W·01)
  ├── intent_extraction       → Parse prompt into structured intent JSON
  ├── part_decomposition      → Build CSG construction tree (complex shapes)
  ├── primitive_planning      → Select primitives, resolve parameters
  ├── dimension_reasoning     → Compute positions, offsets, clearances
  └── verification_planning   → Pre-compute expected volume/bbox/faces

Phase 2: Code Generation (Root RLM)
  └── cadquery_cookbook       → Compile PrimitivePlan → CadQuery Python

Phase 3: Execution (Root RLM)
  └── [Inner Repair Loop × 3]
      ├── repair_guidance     → Fix traceback errors (Repair Sub-Agent)
      └── cadquery_cookbook   → Re-generate corrected code

Phase 4: Mesh Quality (Root RLM)
  └── verification_planning   → Check watertight / manifold / face count

Phase 5: Vision Verification (W·05)
  └── [Outer Refinement Loop × 5]
      └── refinement_guidance → Adjust parameters from visual feedback

Phase 6: Handoff
  └── write_trace() + ForgeCAD export → trace.json + .forge.js
```

---

## Fast Metadata Usage

```python
from tools import read_skill, read_skill_meta, list_skills

# Get metadata only (instant — no full read)
meta = read_skill_meta("cadquery_cookbook")
# → {"name": "cadquery_cookbook", "token_budget": "medium", "used_by": [...], ...}

# Get full skill body (for LLM prompt injection)
body = read_skill("cadquery_cookbook")

# Find all skills tagged for a phase
skills = list_skills(tag="W01")   # → ["intent_extraction", "primitive_planning", ...]
```
