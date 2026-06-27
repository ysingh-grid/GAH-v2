# Phase 2 — connectivity: eyes in the loop, contact-preserving mates, prescriptive diagnostics

## What the run showed (logs/geometry_planning_2026-06-25T10-21-54-615Z.jsonl)
Phases 0/1/1b worked: the agent now builds a COMPLETE chair (hub, 5 legs, 5 casters, gas lift,
seat, backrest, 2 armrests). But it could never make all parts TOUCH into one coherent object, so
it bounced between walls and FINAL'd a fake token. The specific connectivity failures:
- **Floating casters** — placed by absolute, hand-computed positions (`x = 315·cos`), 147 mm from
  the legs (which reach ~290 mm) → "not one object".
- **Seat gap** — mated to the gas-lift top but with `offset:[0,0,25]`, which slid the seat 25 mm
  UP off the mate, breaking the contact `attach` is supposed to guarantee.
- **Carving severs parts** — cut features sliced the base off the body → 2 components.
- **Misleading diagnostics** — reported "seat (nearest backrest 0.0 mm away)" (global nearest, in
  the seat's OWN isolated cluster) instead of "seat is 25 mm from the main body".

Root cause: a BLIND agent is forced to achieve exact geometric connectivity through coordinates
and mates it cannot visually verify.

## The three fixes
### #1 (capability leap) — eyes in the loop
`cad_kernel/fidelity.py` gains `spatial_critique(...)`: a render-grounded vision description focused
on connectivity ("which parts are floating/disconnected and where"). `build_verify_render`, on a
verdict==FAIL whose failing checks are CONNECTIVITY-related (`component_count` for single_solid or
`assembly_coherent` for assembly), renders the failing geometry and appends the description to
`next_action` as a `VISUAL INSPECTION` line. This gives the otherwise-blind agent sight exactly when
connectivity fails — the "Thinking in 3D" loop from the project's vision memo, using the RLM's
multimodal intelligence as the agent's eyes. Host-side, no engine change. Fail-open (a missing/flaky
vision endpoint just omits the note; verdict unchanged; the agent cannot trigger that path).
Test hook: `FORGECAD_SPATIAL_STUB`.

### #2 (substrate correctness) — `attach.offset` can no longer break a mate
`cad_kernel/kernel.py` projects the post-mate slide (`attach.offset` + legacy `position`) ONTO THE
MATING PLANE — removing its component along the mate normal. So `offset` can only slide a part
ACROSS the contact face, never lift it off. Intentional spacing along the normal uses `gap` (the
dedicated, contact-aware field). This makes `attach`'s promise ("parts touch") unbreakable and
removes the accidental-normal-gap class of disconnections (the seat) by construction.

### #3 (usable feedback) — cluster-relative, prescriptive disconnection diagnostics
`cad_kernel/verify.py` `verify_assembly_coherence` now stores all pairwise distances; when
disconnected, it names the largest cluster as the MAIN BODY and, for each isolated part, reports the
nearest part WITHIN the main body + that gap + a prescriptive hint ("attach 'caster' to 'base' (the
nearest part of the main body) instead of placing it by absolute position"). This replaces the
misleading "0.0 mm to a part in its own isolated cluster" message.

Skills/task reframed: connected parts MUST `attach` to a real target (never hand-compute absolute
coordinates for parts that must touch); `attach.offset` is in-plane (use `gap` for the normal); read
the `VISUAL INSPECTION` line on connectivity failures.

## Honest confidence split (as requested)
- **#2 and #3: HIGH — deterministically proven here** with real CadQuery/MeshLib geometry:
  offset `[0,0,25]` along a top mate is now ignored (parts stay in contact), an in-plane offset
  still slides; the floating-part diagnostic is main-body-relative and prescriptive.
- **#1: mechanism HIGH — proven here (stubbed):** connectivity FAIL attaches a VISUAL INSPECTION;
  vision-unavailable fails open with no crash. **End-to-end efficacy (the live agent now converges
  on a connected chair) is MODERATE-HIGH but only the user's machine can confirm** (Deno + key +
  working vision endpoint). This is grounded in the multimodal model's known scene-description
  ability — not blind hope. Stated plainly so expectations are calibrated.

## Verified here — tests/test_phase1_coherence_fidelity.py (12/12)
Incl. `test_offset_along_normal_preserves_contact`, `test_cluster_relative_prescriptive_diagnostic`,
`test_eyes_in_loop_visual_inspection` (stub → VISUAL INSPECTION; no key → fail-open). Full
regression: all 17 test files pass (PYTHONPATH=repo root, PRIMITIVES_JSON_DATA set). Phase 0/1/1b
all still hold (token unforgeability, coherence, fidelity, bbox-as-output). fast_rlm engine untouched.

## Needs the live machine
Whether the agent, now able to SEE connectivity problems and with `attach` that can't silently break
contact, actually converges on a connected chair (and other complex objects). A working vision
endpoint is required for the eyes; without it the platform degrades to the deterministic geometric +
coherence verdict (fail-open, logged).
