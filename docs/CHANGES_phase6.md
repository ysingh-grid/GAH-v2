# Phase 6 — "delivered nothing" reliability + general capability overhaul

Driven by the office-chair run `logs/geometry_planning_2026-06-26T19-09-15-587Z.jsonl` (with a
reference image): 28 steps, ~24 min, **zero artifacts** — despite a sound + coherent chair existing
mid-run. Root causes were verified in code AND in the bundled fast-rlm engine. The engine was NOT
modified; every fix is host-side. Full diagnosis + per-issue explanations are in `fix.md` (Issues
9–16). Design decisions confirmed with the user: always deliver the best sound candidate; fidelity is
advisory; no domain-specific shape recipes; placement fix is general (not a radial special-case);
parallel subagent exploration ON.

## What changed

1. **Best-candidate checkpoint (deterministic safety net).** `cad_kernel/geometry_server.py` banks the
   best sound+coherent candidate per run (ranked fidelity-pass > sound+coherent) to a per-run file;
   `orchestrator.py` promotes it to `exports/` + render + plan store at run end — even on
   budget-exhaustion with no FINAL (the exact path that lost the chair). `_best_effort_salvage` is
   generalized; `_promote_best_candidate` added; all `_fail` sites thread `checkpoint_path`.

2. **Fidelity → advisory.** The token now mints on geometry + coherence PASS; the vision critic sets
   `trust_tier` (`certified` vs `needs_review`) and gives feedback, but never flips the verdict or
   blocks delivery.

3. **`mcp_call` read-path fixed.** The engine returns the tool result as a JSON STRING; the old
   contract ("the return IS the result") made the agent crash on `.get`. `skills/core.md` +
   orchestrator task instructions now teach the robust idiom `json.loads(r) if isinstance(r,str) else r`
   and ready `call`/`build_verify`/`validate` helpers.

4. **Verified CadQuery idioms skill (KB → push, not pull).** `cadquery_kb_tools.build_idioms_skill`
   distils the KB into an always-in-context cheat-sheet (real signatures + selector grammar + a
   live-verified "these methods DO NOT EXIST" list incl. `taper`). Injected into every agent.

5. **Fast custom-code API lint + auto-RAG.** `cad_kernel/cq_lint.py` catches invented methods before
   the build (precise fix + KB example), high-precision/zero-false-positive; build tracebacks are
   enriched with KB signatures for the declared ops.

6. **General contour primitives.** Added `swept_profile` (arbitrary cross-section along a path) and
   `lofted_sections` (loft through arbitrary sections), and `revolved_profile` gained `end_fillet` —
   object-agnostic *technique* primitives so curves are parameter-filling, not free-code.

7. **Coherent + self-checking placement.** `kernel._rotate_vec` expresses an `attach.offset` in the
   part's rotated frame, so offsets rotate WITH the part — radial/array assemblies (5-star bases,
   spokes, bolt circles) now connect. The deterministic contact check already runs before render and
   reports the exact gap.

8. **Parallel strategy exploration (subagents done right).** `skills/core.md` + task instructions
   teach the root to fan out 2–3 strategy lanes via `batch_llm_query`, each GRANTED
   `mcp=["geometry_kernel","host_tools"]` (the missing piece that made old sub-agents unreliable) and
   self-verifying; a native, host-owned `tools/select_best.py::select_best_candidate` picks the winner
   deterministically. `run.yaml` keeps `max_depth: 1` (correctly: root + one level of children).

## Verification
All **29** test files pass offline:
```
export PRIMITIVES_JSON_DATA="$(cat schemas/primitives.json)"; export PYTHONPATH="$(pwd)"; export RLM_MODEL_API_KEY=dummy
for t in tests/test_*.py; do .venv/bin/python "$t"; done
```
New/updated tests: `test_best_effort_checkpoint` (no-FINAL promotion), `test_advisory_fidelity`,
`test_mcp_readpath`, `test_cadquery_idioms`, `test_cq_lint`, `test_rich_primitives_and_verbs`
(general contours), `test_coherent_placement` (5-star base), `test_parallel_exploration`,
`test_phase1_coherence_fidelity` (advisory contract).

## Honest scope
Deterministic substrate (checkpoint, advisory gating, read-path, idioms, lint, contour primitives,
placement frame, selection + token cross-validity) is proven here. The perceptual quality judgment
(`certified` vs `needs_review`, and whether parallel strategies yield a refined form) needs the live
machine (Deno + vision endpoint + a valid `FORGECAD_VISION_MODEL`) and is not bit-repeatable — but it
can no longer turn a sound, buildable result into nothing.
