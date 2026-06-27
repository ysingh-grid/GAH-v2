# Phase 1b — the bounding box is an OUTPUT the kernel owns (not a self-audit trap)

## What the run showed (logs/geometry_planning_2026-06-25T09-39-39-023Z.jsonl)
Phase 1 worked: the agent built a REAL, complete, coherent office chair (hub + two leg cross-bars
+ four wheels + gas lift + seat + backrest + two armrests) that built as a flawless ONE-component,
watertight, self-intersection-free solid. Yet the run FAILED — the SOLE failing check was
`bbox_matches_declared` (measured `[874.9, 964.7, 1049.8]` vs the agent's declared dims). Because
bbox was part of the geometric verdict, `verdict=FAIL`, so fidelity never even ran, no token was
minted, and after burning the whole budget the agent FINAL'd a FAKE token ("I am unable to obtain
a verification token") which the gate correctly rejected. The agent even invented the right
reconciliation (build → read measured → re-declare) but broke on the wrong field name and gave up.

## Root cause
`overall_dimensions` was a value the AGENT had to declare, which the verifier then audited
declared-vs-measured. For a multi-part mated assembly the overall bounding box is EMERGENT — it
depends on mate-derived coordinates the agent never sees — so the audit forced the LLM to
hand-compute a number the kernel already knows exactly. That is the very anti-pattern the project
removes everywhere else (mates derive coordinates, patterns do the trig, merge does the
bookkeeping). It had become a GLOBAL blocker for any non-trivial object, not chair-specific.

## The fix — bbox becomes an OUTPUT; size-fidelity moves to the intent critic
- `cad_kernel/verify.py` — `bbox_matches_declared` is REMOVED from the gating battery. The verdict
  gates only on real soundness (positive volume, watertight, no self-intersections) + coherence
  (single_solid = one fused component; assembly = per-part sound + one connected contact cluster).
  The measured bbox is REPORTED as `measured_bbox` (+ an informational `bbox_note` vs any declared
  value), never gated.
- `cad_kernel/attestation.py` — `canonical_plan_hash` now ALSO excludes `overall_dimensions` (a
  derived/host-owned field), so the host can record the measured bbox without invalidating the
  token, and the agent never has to hand-compute the overall extent to FINAL. The token still
  attests the GEOMETRY (verified: invariant to overall_dimensions, still sensitive to a primitive
  change).
- `cad_kernel/geometry_server.py` — `build_verify_render` surfaces `measured_bbox` at top level and
  passes it to the fidelity critic.
- `cad_kernel/fidelity.py` — `critique(..., measured_bbox=...)` includes the measured dims in the
  prompt and checks them against any explicit size in the request. So the genuine "right size vs
  the request" check is preserved — relocated to the intent-grounded critic, judged against the
  IMMUTABLE request, not a number the agent typed.
- `orchestrator.py` — after the authoritative build+verify PASS, the host writes the MEASURED bbox
  into `overall_dimensions` (authoritative reconciliation) before save/export. Safe w.r.t. the
  token (overall_dimensions is excluded from the hash).
- `skills/core.md` + task instructions — reframed: the kernel derives the declared bbox + part
  count from the plan (the agent no longer passes them); the overall size is an emergent OUTPUT
  (`measured_bbox`) the host records; set each PART's dimensions exactly; the bbox-reconcile
  instruction is removed.

## Why this is not a bandage (remove-it test) and does not regress
- The removed self-audit caught nothing real for emergent assemblies: each part's dimensions are
  set exactly by the agent (correct by construction); only the aggregate extent was unknowable.
  Removing it lets correct objects through. The real "right size" concern (against a user spec)
  moves to the fidelity critic with the measured numbers.
- Phase 0 (unforgeable token) and Phase 1 (coherence + fidelity) are untouched and still hold:
  single_solid still must be one watertight component; assembly still must be per-part sound +
  contact-coherent; fidelity still gates the token; a blob/dropped-feature still gets no token.
- Generality: this unblocks EVERY object whose overall extent is emergent (every multi-part or
  complex design), not just chairs.

## Verified here (deterministic; vision stubbed)
`tests/test_phase1_coherence_fidelity.py` (9/9) — incl. `test_bbox_is_output_not_gate` (a sound box
with a wildly-wrong declared size now PASSES geometry) and `test_fused_chair_passes_geometry` (the
exact fused chair from the failed run now passes geometry and mints a token; measured_bbox differs
from the rough estimate, proving the host measures the true extent). `tests/test_cad_pipeline.py`
updated (the old `broken_wrong_size` FAIL became `bbox_is_output_not_gate` PASS). Attestation:
token invariant to `overall_dimensions`, still sensitive to geometry. Full regression: all 17 test
files pass (PYTHONPATH=repo root, PRIMITIVES_JSON_DATA set).

## Needs the live machine
Confirming the live agent now reaches a PASS + token on the chair (and other complex objects)
instead of dying on the bbox trap. All host-side logic is proven here with model/vision stubbed.
A working vision endpoint is required for the size-vs-request and anti-blob teeth; otherwise it
degrades to sound + coherent (fail-open, logged).
