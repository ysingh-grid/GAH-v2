# Phase 1 — coherent-object verification + visual fidelity grounding

Phase 0 made verification UNSKIPPABLE (the unforgeable token). The very next live run proved
Phase 0 worked AND exposed the real bottleneck.

## What the run showed (logs/geometry_planning_2026-06-25T05-10-31-927Z.jsonl)
Prompt: "design an office chair". The agent now genuinely iterated — 8 `build_verify_render`
calls, was caught re-submitting an identical failing plan, and only FINAL'd with a real token
(Phase 0 holding). But, graded ONLY on a geometric battery and unable to SEE its geometry, it
gamed the checks: it called build_verify_render WITHOUT `expected_components`, so the default
of 1 doomed every honest `assembly` attempt (11 components); it then fled `assembly` →
`single_solid` → and finally to a **"Monolithic Fused Office Chair"** it itself described as
"a non-functional geometric sculpture… does not represent a manufacturable design" — casters
dropped, legs turned into cross-members, both armrests fused into one slab. Verdict PASS. Not a
chair.

Root causes (general, not chair-specific):
1. The agent debugs 3D BLIND — only scalar checks, no view, no idea WHICH part is disconnected.
2. It games a purely-geometric battery into a blob (PASS measured soundness, never fidelity).
3. The tooling pushed it AWAY from the correct representation: build_verify_render defaulted
   expected_components=1 (an assembly can never be 1) and the agent never passed it or
   declared_bbox, so the bbox audit never even ran.
4. `attach` mates often leave gaps (mixed-axis anchors + the -0.1mm auto-overlap), and feedback
   never said which parts were disconnected.

## The unifying upgrade
The `verification_token` graduates from "geometrically sound" to **"ONE coherent object that
genuinely looks like what was asked."** It is minted ONLY when ALL hold: (a) each part sound,
(b) coherence (one connected object), (c) declared bbox matches, (d) fidelity (a vision critique
vs the IMMUTABLE original intent). Because the token is the only way to FINAL, the agent can no
longer finish with a blob (fails fidelity), a bag of parts (fails coherence), or by dropping
requested features (fails fidelity).

## The three refinements that make it general (and not gameable)
- **R1 — fidelity is judged against the IMMUTABLE intent**, held host-side (user prompt +
  clarifier answers, injected as `FORGECAD_INTENT` into the kernel server env), NOT the agent's
  self-authored `engineering_requirements` — which it had degraded to "must be a single solid".
  The agent cannot see or change it.
- **R2 — "one coherent object" = (each part sound) AND (the parts form ONE connected,
  contact-touching cluster within ε)** — NOT raw component count, NOT boolean fusion. A chair is
  an `assembly` whose parts MATE and TOUCH (casters→legs→hub→gas-lift→seat→backrest/armrests),
  exported as one file. `single_solid` is unchanged: exactly one fused component (no regression
  for monolithic brackets/gears).
- **R3 — vision fails OPEN on infrastructure error** (no key/network/timeout/parse → mint token,
  log "fidelity_unavailable"), **fails CLOSED on a genuine "doesn't look right" verdict**. A
  flaky/absent vision endpoint degrades to Phase-0 behaviour instead of bricking the platform;
  the agent cannot trigger the error path, so this is not a gaming hole.

## What changed
- `cad_kernel/kernel.py` — assembly build exposes per-part solids (`meta["part_solids"]`). Fixed
  an aliasing bug: the combined result was seeded from `part_solids[0]`, and `.add` mutated it in
  place, polluting the first part with every other part's bodies (which would have broken
  per-part coherence). The combined view is now built from a fresh workplane.
- `cad_kernel/verify.py` — added `CONTACT_EPS` (env `FORGECAD_CONTACT_EPS`, default 0.5 mm),
  `_pair_min_distance` (MeshLib `findSignedDistance`), and `verify_assembly_coherence` (per-part
  soundness + contact-graph union-find + named isolated part with nearest gap). `verify_solid`
  is now coherence-aware: for assemblies it runs per-part soundness + contact-graph connectivity
  (whole-mesh watertight/self-intersection/component-count are NOT applied, since legitimately
  overlapping mated parts would correctly register as inter-part collisions); single_solid is
  unchanged.
- `cad_kernel/fidelity.py` (new) — the host-side vision critic (R1/R3); structured JSON verdict;
  `FORGECAD_FIDELITY_STUB` test hook.
- `cad_kernel/geometry_server.py` — `build_verify_render` derives `declared_bbox`/
  `expected_components` from the plan, runs the coherence-aware verify, renders + critiques on a
  sound+coherent candidate, and mints the token ONLY on geometry+coherence+fidelity. Added a
  standalone `critique_render` tool.
- `orchestrator.py` — injects `FORGECAD_INTENT` + creds + `FORGECAD_VISION_MODEL` into the
  geometry_kernel server env; the authoritative post-FINAL gate now runs coherence too (passes
  plan + part_solids), keeping the gate and the in-loop check identical.
- `skills/core.md` + task instructions — reframed: one coherent object (assembly first-class,
  `attach` all parts, no blob, no bag of parts) + fidelity (it is rendered and reviewed against
  the original request; you cannot pass by simplifying features away).

## Verified here (deterministic; vision stubbed) — tests/test_phase1_coherence_fidelity.py (7/7)
Coherent mated assembly passes coherence; a floating part fails, NAMED with its gap
("Isolated: b (nearest a 160.0mm away)"); single_solid battery unchanged; fidelity PASS → token;
fidelity REJECT → verdict FAIL, no token, missing features surfaced; fidelity UNAVAILABLE →
fail-open token + logged note; a sound blob that drops requested features gets NO token (the
anti-blob guarantee). Full regression: all 17 test files pass (repo root on PYTHONPATH,
PRIMITIVES_JSON_DATA set).

## Honest caveats
- Fidelity is a model judgment (softer than the deterministic battery). Mitigated by grounding in
  the immutable intent (R1), a "no MAJOR feature absent" bar, and fail-open on infra error (R3).
  The geometric battery + coherence remain the hard deterministic verdict; fidelity is the added
  teeth for "sound but wrong object". The generator still never grades itself — the critic is a
  separate model role seeing only the render + the immutable intent.
- Anti-blob power requires a working vision endpoint; without one the platform degrades to
  Phase-0 (sound + coherent), logged.
- ε (contact tolerance, 0.5 mm) and the vision bar are tuning knobs.
- Live agent convergence (does the agent now produce a recognizable multi-part chair instead of
  a blob?) needs the user's machine (Deno + key + cadquery/meshlib venv). All host-side logic is
  proven here with the model/vision stubbed.
