---
name: part_decomposition
version: "1.0"
purpose: >
  Decompose a complex 3D shape described in a prompt into an ordered sequence
  of CSG operations on simple primitives (base → unions → cuts → finish).
  Used before primitive_planning to create the construction tree.
used_by:
  - planner (decomposition step, for multi-primitive shapes)
inputs:
  - user_prompt: "Raw natural-language design request"
  - intent: "Output of intent_extraction skill"
outputs:
  - construction_tree: "Ordered list of {id, role, primitive_type, operation} steps"
tags: [planning, CSG, decomposition, phase1]
token_budget: low   # ~400 tokens — load only for multi-primitive shapes
---

# Skill: Part Decomposition

Decompose complex 3D geometry into a **CSG construction tree** before building
the PrimitivePlan. Used for multi-primitive shapes in **Phase 1**.

Most complex mechanical parts follow this pattern:

```
Base Solid  (+addition solids)  (−subtraction solids)  [+finish features]
```

---

## Decomposition Roles

| Role | Operation | Description |
|---|---|---|
| **Base** | `base` | Largest/dominant primitive. Starting point. |
| **Feature** | `union` | Fused additions — bosses, ribs, tabs, flanges |
| **Pocket** | `cut` | Carved subtractions — holes, slots, pockets, counterbores |
| **Finish** | `fillet`/`chamfer` | Applied last — stress relief, handling, appearance |

---

## Decomposition Checklist

1. **Identify the Base Solid**
   - Largest dominant shape (e.g., main cylinder of a flange, main block of bracket)
   - Always the first step in the construction tree

2. **Identify Additions (Union)**
   - Fused protrusions: boss extrusions, ribs, lugs, tabs
   - Each becomes a `union` step with its own primitive

3. **Identify Pockets (Cut)**
   - Carved features: through-holes, blind pockets, slots, counterbores
   - Each becomes a `cut` step — remember to use the `+2mm / +1mm offset` rule

4. **Identify Finish Features**
   - Fillets, chamfers, shells
   - Always applied **after** all CSG is complete

---

## Example: Flanged Mount

| Step | Role | Primitive | Key Parameters |
|---|---|---|---|
| 1 | base | cylinder | outer_r=50, height=10 |
| 2 | union | cylinder | outer_r=25, height=30, z_offset=20 |
| 3 | cut | cylinder | outer_r=15, height=42, z_offset=-1 (hollow) |
| 4 | cut×4 | cylinder | r=3.3, height=12, radial=38 (mount holes) |
| 5 | finish | chamfer | 1mm on outer top edge |

> **Rule**: Build the construction tree first, then pass it to
> `primitive_planning` to assign library schemas and resolve all parameters.

---

## When to hand off vs design in one context

You have a way to hand a piece of the design off to be planned separately in
parallel. Use it when, and only when:

### Case A — Independent Solids (hand off)
Distinct bodies that only meet at an interface. Each designs freely in its own local frame.
- Cricket bat → `["blade", "handle"]`
- Bolt + nut → `["bolt", "nut"]`

### Case B — Features of One Connected Body (do NOT hand off — plan inline)
Hub+spokes+rim, flange+bolt-bosses+ribs. These are one connected body, not
independent solids — plan them yourself as a single construction tree
(`base` → `union` → `cut` → finish). Fix your own shared anchors first: every
shared radius, plane, or bolt-circle position, decided once and reused
consistently across steps. Every union feature must overlap the body it joins
by 0.5–1mm (a feature that only touches — tangent/coincident face — does NOT
fuse; see `dimension_reasoning` Rule 2).

**Wheel example** (Case B, plan inline): hub cyl r=15, rim ring inner=40/outer=44,
spoke spanning r=14..41 (overlaps hub & rim by ~1mm), polar ×5 — all as steps
in one plan: `[hub(base), spoke×5(union, pattern=polar), rim(union)]`.

### RULE: Only hand off for genuinely independent solids
A single connected body with many features — however many fillets, shells,
patterns, or holes — is NOT a hand-off case. Design it in one context. Only
a true multi-solid assembly (Case A) warrants a hand-off, and even then only
after you've fixed the shared anchors every piece must agree on.

---

## Case A hand-off with `delegate_features` (worked example)

For a genuine multi-body assembly, use `delegate_features(features, shared_frame)`.
It plans each body in a parallel child agent, then you FLATTEN the results.

**1. Fix the shared frame first** — the anchors every body must agree on:

```python
shared_frame = {
    "leaf_thickness": 4.0, "leaf_len": 40.0, "leaf_w": 30.0,
    "pin_axis_z": 4.0, "pin_radius": 2.5, "knuckle_overlap_mm": 1.0,
}
bodies = await delegate_features(
    features=[
        {"name": "leaf_a", "operation": "base",  "placement": [-20, 0, 0],
         "candidate_primitives": ["box", "filleted_box"], "notes": "left leaf"},
        {"name": "leaf_b", "operation": "union", "placement": [ 20, 0, 0],
         "candidate_primitives": ["box", "filleted_box"], "notes": "right leaf"},
        {"name": "pin",    "operation": "union", "placement": [0, 0, 4],
         "candidate_primitives": ["cylinder"],
         "notes": "spans both leaves along X; extend 1mm into each knuckle"},
    ],
    shared_frame=shared_frame,
)
```

**2. Flatten in order** — concatenate every body's steps into one `steps` list.
Each child returns a valid plan starting with its own `base`; when concatenated
the 2nd+ bases are auto-coerced to `union` (a union of disjoint solids is one
legal compound). So you get exactly one `base`, the rest `union`.

**3. Preview the assembly, then FINAL:**

```python
plan = {"part_name": "hinge", "steps": [s for body in bodies for s in body]}
ev = preview_plan(plan)
# If ev["num_components"] > 1, the bodies only TOUCH — grow the pin / leaf overlap
# at the knuckles by ~1mm (use shared_frame["knuckle_overlap_mm"]) and re-preview.
FINAL(plan)
```

> **Why per-body children help:** each body is planned in a clean context with
> only its own concern + the shared frame, so a 4-body assembly does not blow up
> one monolithic context. The shared_frame is what keeps them aligned; the
> assembly preview is what proves they actually fuse.
