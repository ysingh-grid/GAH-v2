# CAD RLM — Skills Reference

> All skills follow **Claude Skills Style**: a YAML frontmatter metadata block
> at the top, followed by a Markdown body. This lets the system read metadata
> instantly (no LLM tokens) and load bodies only when needed.

---

## Skill File Format

```
skills/
├── SKILLS.md                 ← this file (master reference)
├── overview.md               ← pipeline map + quick-start
├── intent_extraction.md      ← Phase 1, Step 1
├── part_decomposition.md     ← Phase 1, Step 1.5 (complex shapes)
├── primitive_planning.md     ← Phase 1, Steps 2–3
├── dimension_reasoning.md    ← Phase 1, Steps 2–3 (math)
├── cadquery_cookbook.md      ← Phase 2 — code generation
├── verification_planning.md  ← Phase 3–4 — quality thresholds
├── repair_guidance.md        ← Phase 3 — inner repair loop (max 3)
└── refinement_guidance.md    ← Phase 5 — outer refine loop (max 5)
```

Each `.md` file starts with a `---` YAML frontmatter block:

```yaml
---
name: <skill_name>
version: "1.0"
purpose: >
  One-paragraph description of what this skill does.
used_by:
  - <worker or sub-agent name>
inputs:
  - <input_name>: "description"
outputs:
  - <output_name>: "description"
tags: [tag1, tag2, ...]
token_budget: low | medium | high
---
```

---

## Loading API — `tools/read_skill.py`

```python
from tools import read_skill, read_skill_meta, read_skill_body, list_skills
```

| Function | Returns | Speed | When to use |
|---|---|---|---|
| `read_skill(name)` | `str` — full file | fast | Inject entire skill into LLM prompt |
| `read_skill_body(name)` | `str` — body only | fast | Inject body without YAML header |
| `read_skill_meta(name)` | `dict` — metadata | ⚡ instant | Select which skills to load; zero tokens |
| `list_skills()` | `list[str]` | fast | All skill names |
| `list_skills(tag="W01")` | `list[str]` | fast | Skills filtered by tag |

### Examples

```python
# Check token budget before loading
meta = read_skill_meta("cadquery_cookbook")
if meta["token_budget"] == "medium":
    body = read_skill_body("cadquery_cookbook")   # only body, no YAML header

# Find all Phase-1 planning skills
planning_skills = list_skills(tag="phase1")
# → ["dimension_reasoning", "intent_extraction", "part_decomposition", "primitive_planning"]

# Find which skill handles the inner repair loop
repair_skills = list_skills(tag="inner-loop")
# → ["repair_guidance"]
```

---

## Skills at a Glance

### 1. `intent_extraction`
| Field | Value |
|---|---|
| **Phase** | 1 — Step 1 |
| **Used by** | `planning_worker` (W·01) |
| **Token budget** | `low` |
| **Tags** | `planning`, `intent`, `parsing`, `W01`, `phase1` |

**What it does**: Parses a user's free-form CAD prompt into a structured JSON
object: `{target_object, dimensions, constraints}`. This is the very first step
of every design request.

**Key output**:
```json
{
  "target_object": "cone",
  "dimensions": {
    "base_diameter": { "value": 30.0, "unit": "mm", "type": "explicit" }
  },
  "constraints": { "watertight": true }
}
```

---

### 2. `part_decomposition`
| Field | Value |
|---|---|
| **Phase** | 1 — Step 1.5 *(optional — complex shapes only)* |
| **Used by** | `planning_worker` (W·01) |
| **Token budget** | `low` |
| **Tags** | `planning`, `CSG`, `decomposition`, `W01`, `phase1` |

**What it does**: Breaks a complex shape into a **CSG construction tree** before
building the PrimitivePlan. Maps each feature to a role: `base`, `union`,
`cut`, or `finish`.

**When to use**: Only when the shape has 2+ primitives (e.g., flanged cylinder,
box with through-holes, stacked assembly).

---

### 3. `primitive_planning`
| Field | Value |
|---|---|
| **Phase** | 1 — Steps 2–3 |
| **Used by** | `planning_worker` (W·01) |
| **Token budget** | `low` |
| **Tags** | `planning`, `primitives`, `CSG`, `W01`, `phase1` |

**What it does**: Converts the intent + construction tree into a full
`PrimitivePlan` JSON — assigns library primitive names, resolves all parameter
values, and defines positions + orientations for every step.

**Key output**:
```json
[
  { "id": "body", "primitive": "cylinder", "operation": "base",
    "parameters": {"radius": 20.0, "height": 50.0},
    "position": [0, 0, 0], "orientation": [0, 0, 0] }
]
```

---

### 4. `dimension_reasoning`
| Field | Value |
|---|---|
| **Phase** | 1 — Steps 2–3 *(integrated into primitive_planning)* |
| **Used by** | `planning_worker` (W·01), `repair_sub_agent` |
| **Token budget** | `low` |
| **Tags** | `geometry`, `math`, `positioning`, `alignment`, `W01`, `phase1` |

**What it does**: Provides the geometry math rules for correct placement:
- **Half-height stacking rule**: `z = base_H/2 + shaft_H/2`
- **Cutter offset rule**: cutters must be `H+2mm` tall, offset `1mm` outward
- **Union overlap rule**: solids must overlap ≥ `0.1mm` before `.union()`
- **Volume formulas** for predicting theoretical volume

---

### 5. `cadquery_cookbook`
| Field | Value |
|---|---|
| **Phase** | 2 — Code Generation |
| **Used by** | `planning_worker` (code gen), `repair_sub_agent`, `refine_sub_agent` |
| **Token budget** | `medium` |
| **Tags** | `codegen`, `cadquery`, `API`, `patterns`, `W01`, `phase2` |
| **Contract** | Script must `import cadquery as cq` and assign final solid to `result` |

**What it does**: Authoritative cheat-sheet of correct CadQuery v2 API patterns.
The code generator **must** follow these exactly. Key rules:
- `.cone()` and `.torus()` don't exist — use `cq.Solid.makeCone(r1, r2, h)`
- Cylinder signature: `cylinder(height, radius)` — height comes first
- Hollow cylinder: `circle(outer).circle(inner).extrude(h)`

---

### 6. `verification_planning`
| Field | Value |
|---|---|
| **Phase** | 3–4 — Mesh Quality & Verification |
| **Used by** | `planning_worker` (W·01), `verifier_worker` (W·05) |
| **Token budget** | `low` |
| **Tags** | `verification`, `geometry`, `quality`, `W01`, `W05`, `phase3`, `phase4` |

**What it does**: Defines expected geometry metrics **before** execution so
failures are caught immediately:
- Theoretical volume formulas for all 13 primitives
- Expected bounding box `[xmin, xmax, ymin, ymax, zmin, zmax]`
- Minimum expected face counts per primitive type
- Mesh quality pass/fail thresholds (`is_watertight`, `open_edges`, `passes`)
- Repair trigger logic (when to invoke Repair Sub-Agent)

---

### 7. `repair_guidance`
| Field | Value |
|---|---|
| **Phase** | 3 — Inner Repair Loop *(max 3 attempts)* |
| **Used by** | `repair_sub_agent` only |
| **Token budget** | `medium` |
| **Tags** | `repair`, `debugging`, `cadquery`, `errors`, `W01`, `inner-loop` |
| **Contract** | Return ONLY corrected Python code. No markdown. Assign solid to `result`. |

**What it does**: Helps the Repair Sub-Agent identify the root cause of
CadQuery execution tracebacks. Covers the 5 most common errors:
1. `AttributeError: no attribute 'cone'` → use `makeCone`
2. Non-manifold solid → extend cutter, add overlap
3. Empty face selector → use `#Z` or `.item(0)`
4. Syntax / import errors
5. `.union()` / `.cut()` type mismatch

---

### 8. `refinement_guidance`
| Field | Value |
|---|---|
| **Phase** | 5 — Outer Refinement Loop *(max 5 attempts)* |
| **Used by** | `refine_sub_agent` only |
| **Token budget** | `low` |
| **Tags** | `refinement`, `feedback`, `geometry`, `W05`, `outer-loop` |
| **Contract** | Return ONLY corrected Python code. No markdown. Assign solid to `result`. |

**What it does**: Translates verifier visual feedback into targeted geometry
fixes. Covers the 5 most common visual/geometric issues:
1. **Size mismatch** — radius vs. diameter confusion
2. **Position offset** — re-apply half-height stacking rule
3. **Missing features** — missing `.cut()` or undersized cutter
4. **Orientation errors** — wrong `.rotate()` axis
5. **Score < 60** — full checklist re-check

---

## Token Budget Guide

| Budget | Approximate tokens | Strategy |
|---|---|---|
| `minimal` | < 100 | Always load (e.g., `overview`) |
| `low` | 200–500 | Load for every planning call |
| `medium` | 500–1000 | Load only when that sub-agent is triggered |
| `high` | 1000+ | Load only for final complex prompts |

> **Tip**: Use `read_skill_meta(name)["token_budget"]` to decide whether to
> load a skill before spending tokens on it.

---

## Tag Reference

| Tag | Meaning |
|---|---|
| `W01` | Used during W·01 Planning activity |
| `W05` | Used during W·05 Verification activity |
| `phase1` | Phase 1 — Planning |
| `phase2` | Phase 2 — Code Generation |
| `phase3` | Phase 3 — Execution / Repair |
| `phase4` | Phase 4 — Mesh Quality |
| `inner-loop` | Inner repair loop (max 3 — triggered on compile failure) |
| `outer-loop` | Outer refinement loop (max 5 — triggered on vision failure) |
| `planning` | Intent / structure analysis skills |
| `codegen` | Code generation skills |
| `repair` | Error recovery skills |
| `refinement` | Visual feedback adjustment skills |
| `geometry` | Math / positioning skills |
| `verification` | Quality checking skills |
| `meta` | About the skill system itself |
