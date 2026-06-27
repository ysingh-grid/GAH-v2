# ForgeCAD v5 — capability builds (on top of v4)

v4 made the agent stateful and removed the bandages. v5 raises the GEOMETRY ceiling and adds
inter-run statefulness. Everything here is deterministic where determinism has a single right
answer (a geometric or bookkeeping invariant), never to paper over a reasoning step — and every
change is verified against real CadQuery geometry, not just syntax-checked.

## 1. Expanded mate algebra (`cad_kernel/kernel.py`, `schemas/geometry_plan.py`)
The relational `attach` vocabulary was six planar faces. Now:
- **Edge anchors** — `at: "top|front"` mates to the midpoint of a shared edge.
- **Corner anchors** — `at: "top|front|right"` mates to a vertex.
- **`attach.offset`** — `[dx,dy,dz]` relative slide after the mate, for off-centre placement on a
  face while keeping the faces in contact.
Anchor points are the averaged centre of all sub-shapes the combined selector matches, so they
stay well-defined; an anchor that matches nothing raises an actionable error (the agent fixes it
in-loop). Impossible anchors (`top|bottom`) are rejected at schema time. Single-face mates behave
exactly as before (verified by regression).

## 2. Feature patterns (`cad_kernel/kernel.py`, `schemas/geometry_plan.py`)
`pattern` on a step repeats a feature so the KERNEL computes the instance transforms — the planner
never hand-computes orbit/array coordinates (the same class of error `attach` removes):
- `{kind:"linear", count, step:[dx,dy,dz]}`
- `{kind:"radial", count, axis, center, sweep_deg}`
Scoped to features that fuse/cut into a body (operation join/cut/intersect) so component counting
stays exact; separate repeated bodies use explicit steps. Verified: a radial bolt-circle's volume
matches the analytic value to the digit.

## 3. Deterministic recursive merge (`cad_kernel/merge.py`, exposed as `merge_subplans`)
The parent agent reasons about which parts exist and how they connect; `merge_subplans` does the
single-right-answer stitching it should not do by hand — namespacing names, rewiring intra-part
mates, renumbering sequence_ids, tagging parts, applying cross-part `connections`. Verified: the
merged plan validates against `GeometryPlan` and builds into one valid solid.

## 4. Inter-run statefulness (`plan_store.py`, orchestrator)
Because the kernel is deterministic (same plan -> same solid), the plan JSON is a complete,
replayable state object. v5 content-addresses and persists every accepted plan, and adds an opt-in
EDIT MODE: `FORGECAD_EDIT=<id|label|latest>` loads a prior plan and the agent modifies it minimally
("make the column taller") instead of starting over. This is the to-and-fro iteration the platform
was always meant to support. The store is verified; the live edit loop needs your machine to tune.

## The line held throughout
Determinism was added ONLY where there is one correct answer: mate coordinates, pattern transforms,
merge bookkeeping, plan hashing. The verifier stays fixed and unskippable; the generator never
grades itself. The remove-it test still holds for every addition — remove it and quality drops
because the model would otherwise hand-compute trig or drop a reference, not because it masks a
reasoning step.

## Verified here vs needs your machine
Verified with real CadQuery 2.8 + Pydantic in this build: composite anchors, offset, linear/radial
patterns (incl. analytic volume check), merge structure + real build, schema accept/reject of all
new fields, plan-store round-trip, full regression. Needs your machine (Deno + key + meshlib venv):
live agent convergence and the edit-mode loop end-to-end.
