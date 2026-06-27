# Phase 5 — Determinism-first reliability fixes

Driven by two real failing "office chair" runs that delivered **nothing**:
- **Run 1** died from recursion garbage + custom-code/tool-name typos until budget ran out.
- **Run 2** built a chair but couldn't connect patterned casters to patterned legs, looped 9×
  on the coherence check, then **fabricated a token** → the gate rejected it → total loss.

## Governing principle
Every change is classified by whether it helps **deterministically** (host-enforced; works
regardless of whether the agent cooperates) or **non-deterministically** (depends on the agent
reading guidance / the perceptual vision loop). Tier A is implemented with confidence; Tier B is
implemented but **explicitly flagged** as not-guaranteed.

---

## TIER A — deterministic, host-enforced

### A1. In-loop schema validation (`cad_kernel/geometry_server.py`)
`build_verify_render` previously ran the RAW plan dict through the kernel; the `GeometryPlan`
pydantic contract was only enforced at FINAL. So a plan could "pass geometry" yet be
**un-FINAL-able** — e.g. `pattern`+`operation:"new"` (exactly Run 2's casters), which the
schema's `_validate_patterns` forbids. Added `_validate_plan_schema(plan)` and a check at the top
of the new shared impl `_build_verify_render_impl`: an invalid plan returns
`{stage:"validate", ok:False, errors, next_action}` with **no token**, and the pattern case is
pointed at the working construction (explicit per-instance `attach`). This deterministically
collapses the 9-iteration doom loop into one clear, early redirect. Fail-open if the validator
itself can't load (don't block on our own import problem).
Tests: `tests/test_buildloop_schema.py`.

### A2. Recursion off by default (`run.yaml`, `orchestrator.py`, `skills/core.md`)
`max_depth: 2 → 1` (root only; sub-agents cannot be spawned), so Run 1's garbage sub-plans
(zero-dim plans, invented `star` primitive) become **impossible**, not merely discouraged.
Removed the `load_skill('assembly')`/recursion steering from the task instructions and core.md.
The assembly skill file and `merge_subplans` tool are left in place.

### A3. Host-side tolerance for the THREE observed tool mistakes (`cad_kernel/geometry_server.py`)
- Registered alias tool `build__verify_render` (double underscore) → same impl.
- PASS return now carries the token under **both** `verification_token` and `token`.
- `render_format` kwarg accepted and ignored.
These deterministically turn the observed failures into successes. **Flag:** this covers only the
*observed* patterns; novel typos still fail, because tool-name resolution lives in fast-rlm
(untouched).
Tests: `tests/test_tool_tolerance.py`.

### A4. Best-effort checkpoint — decouple run-yield from the token decision (`orchestrator.py`)
Added `_best_effort_salvage(plan_dict)`: when the agent's FINAL is rejected (no/forged token, or a
gate failure), the host re-builds + re-verifies the plan and, **only if it is geometrically sound
+ coherent (verdict PASS)**, exports STL/STEP + a render tagged `besteffort_` and clearly labeled
"NOT agent-confirmed". It is never certified and never saved as an accepted plan. `_fail(...)` now
calls it when given the plan, then still raises `PipelineError` (a failure stays a failure). This
runs host-side regardless of the agent, so a rejected run yields a reviewable artifact instead of
nothing — without weakening the coherence guarantee (broken/non-coherent plans salvage nothing).
Tests: `tests/test_best_effort_checkpoint.py`.

---

## TIER B — implemented but FLAGGED (non-deterministic in impact)

### B2. Minimal honest guidance (`skills/core.md`, `orchestrator.py`)
Added an "EXACT TOOL CONTRACT" block (correct tool name / `plan=` only / no `render_format` /
read `verification_token`) and strengthened the repeated-connected-parts guidance (explicit
per-instance `attach`; never `pattern` separate bodies). **Flag:** guidance only helps if the
agent reads/follows it.

### B3. VLM feedback robustness + render cues (`cad_kernel/render.py`, `fidelity.py`, `geometry_server.py`)
- `render.py`: named views (front/side/top/iso) + a labeled X/Y/Z **axis triad** in every panel,
  so orientation can be reasoned about precisely. Signature/return unchanged.
- `fidelity.py`: `critique()`/`spatial_critique()` accept optional `part_names`; the critic is
  asked for **structured per-part** directives `{part, issue, fix}`. `_verdict_from_payload`
  flattens these to a back-compatible `missing_major_features: list[str]` and also exposes
  `missing_features_structured`.
- `geometry_server.py`: passes the plan's part names to the critic; the eyes-in-the-loop spatial
  critique now fires on **any** geometry/coherence failure (was connectivity-only). All fail-open.
- **Flag:** these improve the INPUTS to the perceptual loop; they do **not** deterministically fix
  orientation/form quality — that remains perceptual and depends on a live vision endpoint.
Tests (stub-based, deterministic): `tests/test_vlm_feedback.py`.

---

## DROPPED: module / group-pattern capability
A `module` construct (or kernel auto-replication of attach across a patterned target) was
considered and **deliberately dropped**: its real-run benefit depends on **non-deterministic agent
adoption**, and A1 already removes the casters doom loop deterministically by rejecting the broken
pattern usage early and pointing to the proven explicit per-instance path. Adding it would be
complexity without a deterministic payoff.

---

## Verification
- Full suite: **23/23 green** (19 prior + 4 new: `test_buildloop_schema`, `test_tool_tolerance`,
  `test_best_effort_checkpoint`, `test_vlm_feedback`). Run with
  `export PRIMITIVES_JSON_DATA="$(cat schemas/primitives.json)"; export PYTHONPATH="$(pwd)"; export RLM_MODEL_API_KEY=dummy`
  then `for t in tests/test_*.py; do .venv/bin/python "$t"; done`.
- fast-rlm engine was **not** modified.

## Honest scope (proven offline vs. needs the live machine)
- **Proven deterministically here** (no vision endpoint / no Deno): A1, A2, A3, A4 and the B3
  plumbing (render cues exist, structured feedback flows, spatial critique fires).
- **Requires the user's live machine** (real vision endpoint + key + a valid `FORGECAD_VISION_MODEL`
  / model name in `run.yaml`, which the USER must set): whether B2/B3 actually improve orientation
  and form quality. That is the perceptual loop and is **not** bit-repeatable.
- A1–A4 deterministically stop the runs from *dying* (doom loop, garbage sub-plans, tool typos,
  total loss). No change makes a run produce a "good chair" deterministically — form quality lives
  in the perceptual VLM loop.
