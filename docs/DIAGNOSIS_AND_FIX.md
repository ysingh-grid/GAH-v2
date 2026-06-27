# Diagnosis of the uploaded version, and the real fix

## What was actually wrong (confirmed from your run logs)

Your latest run log showed **0 `ask_user` calls and 0 `declare_gap_ledger` calls** —
the model simply ignored the 🚨 "6-CALL protocol". Two consequences followed, and
together they were the error you couldn't place:

1. **Self-inflicted rejections.** Four validators in `geometry_plan.py` rejected
   legitimate plans:
   - `_validate_pattern_grouping` rejected >5 of any primitive — but a chair has 5
     legs + 5 casters = 10 cylinders, so every chair was rejected.
   - the duplicate-rationale check rejected 5 legs that share one honest rationale.
   - `_validate_bounding_box_consistency` (a fragile 1.5× rule) false-rejected normal parts.
   - `_validate_clarifications_were_asked` read `.gap_ledger.json` from disk and raised
     **"No gap ledger was declared"** whenever the model skipped `declare_gap_ledger`.

2. **"Valid, then rejected."** A `GEOMETRY_PLANNING_SANDBOX` flag made `validate_plan`
   (in the sandbox) **skip** the gap-ledger check and return valid=True, while the host
   post-validation **enforced** it. So the model validated clean, called FINAL, and was
   then rejected by a check it was never allowed to see. Maddening, and the root of the
   confusion.

The deeper lesson: **piling imperative threats into the prompt does not change a model's
tool-calling behaviour** (the logs prove it), and **coupling a data-contract (the schema)
to session files + sandbox-conditional enforcement** guarantees inconsistency.

## The real fix (not a bandage)

1. **The schema is now a PURE geometry validator.** Removed all four bandage validators
   and every `.gap_ledger.json` / `GEOMETRY_PLANNING_SANDBOX` coupling. `validate_plan`
   (the host tool the model calls) and the post-FINAL check are now **identical** — there
   is no hidden divergence, so "valid then rejected" cannot happen. A chair's 10 cylinders
   and repeated rationales validate and build. Kept the legitimate checks: sequential ids,
   rationale length, real primitive types, exact parameters, hollow-wall sanity.

2. **Asking is fixed structurally, not by threats.** A dedicated **clarifier pass** runs
   in the orchestrator BEFORE planning: one focused model call whose ONLY job is to surface
   up to 3 critical questions (it has no competing objective, so it actually asks). The
   orchestrator then calls `ask_user` for each, and injects the answers into the planning
   task as established facts. The planning agent cannot skip asking, because asking already
   happened in a separate step. Fully fail-safe: any error → planning proceeds without it;
   an unreachable user → the answer is dropped, never logged as a fake clarification. The
   orchestrator owns the final `clarifications` (so they are real by construction). Toggle
   with `clarify: true` in run.yaml.

3. **Removed the dead machinery.** `declare_gap_ledger` (tool + schema coupling), the
   `GEOMETRY_PLANNING_SANDBOX` env hack, and the 🚨 6-call protocol in `core.md` are gone.
   `core.md` and the task instructions are now a clean sequence: get primitives → draft
   (primitive-first; `custom` when none fits) → `validate_plan` → FINAL.

4. **Fixed a real bug in your kernel.** Your custom-step isolation used multiprocessing
   `spawn`, which re-imports `__main__` and crashes depending on how the parent was
   launched, and round-tripped the solid through **STL** (tessellated) so it could no longer
   boolean cleanly with primitives. Replaced with a standalone runner subprocess that
   transfers a true **BREP** — robust isolation, a real timeout, and exact booleans. Verified:
   custom-only, custom+primitive union, and an infinite-loop timeout all behave correctly.

## Verified here, end to end (no LLM)
- `tests/test_validation_boundaries.py` (12/12): legitimate rejections still reject; the
  previously-bandaged cases (10 cylinders, duplicate rationales, large parts, assumptions
  without clarifications) now correctly pass.
- `tests/test_validation_and_placement.py`, `test_cad_pipeline.py`, `test_host_mcp.py`,
  `test_planning_substrate.py`: all pass.
- A realistic 13-step office chair: `validate_plan` valid → builds (all steps) → one
  watertight component → renders. The earlier verdict FAIL was the honest declared-vs-measured
  bbox audit; with accurate dims it passes all five checks.
- Clarifier plumbing proven with a stubbed model: asks, gathers Q&A, degrades safely,
  drops unreachable-user sentinels.

## Needs your machine (Deno + key)
The live quality of the clarifier's questions and the planning agent's drafting. The
substrate they depend on — the consistent schema, the clarifier wiring, the validation
oracle, the robust kernel — is verified here.

---

# Round 2 — why it failed AGAIN, and the actual robust fix

## What the new log showed
The model did exactly three things: printed the schema, fetched primitives, then called
`FINAL(...)` with `rounded_box` — and **never called `validate_plan`** (confirmed: 0 calls
in the trace). The host post-validation then correctly rejected `rounded_box` (it genuinely
is not a real primitive) and the run **crashed** with `raise e`.

## The honest root cause
My previous fix added `validate_plan` and *instructed* the model to call it before FINAL.
That left a correctness-critical check **depending on the model's compliance** — and this
model skips it, just as it skipped the gap-ledger threats. Rejecting `rounded_box` is
correct; **crashing instead of recovering** was the bug. Validation must never depend on the
model volunteering to call a tool.

## The fix: orchestrator-owned validation + auto-repair (no model dependence)
Post-validation in `orchestrator.main()` is now an UNCONDITIONAL, bounded repair loop:
1. Validate the FINAL plan with the real schema (always — independent of whether the model
   called `validate_plan`).
2. If invalid, feed the EXACT errors + the list of valid primitive types back to the model
   as a focused repair task ("replace the invalid primitive_type with the nearest real one,
   e.g. `rounded_box` → `filleted_box`, or a `custom` step"), re-plan, and re-validate.
3. Repeat up to `max_validation_repair_attempts` (default 3). Only raise — with a clean,
   explicit error and the trace — if repair is exhausted.

Fixing a *stated* error is something the model does reliably (unlike remembering to validate
proactively), so this converts the common failure into an automatic recovery.

## Verified here by reproducing your EXACT failure (LLM stubbed, everything else real)
- Model FINALs `rounded_box` and skips `validate_plan` → orchestrator runs VALIDATION REPAIR,
  gets the corrected plan, and completes build → verify (all 5 checks PASS) → render. No crash.
- Worst case (model never fixes it) → 3 bounded attempts → one clean `ValueError` with the
  exact error, no mid-pipeline crash.
- All five test suites still pass.

---

# Round 3 — the office-chair run (Edge.fillet) and the grounding question

## What the log actually showed
This run was NOT the rounded_box one. The model behaved BETTER: it used 5 `custom` steps
(grounded in CadQuery) plus boxes and cylinders. Two things still got it rejected — and both
were over-strict CONTRACTS, not model failures:

1. **`Edge.fillet` rejected.** The model declared `cadquery_operations` including `Edge.fillet`
   — a REAL CadQuery operation. But the curated KB is a SUBSET of CadQuery's API, and the
   validator treated "not in the KB" as "invalid", so it hard-rejected a valid plan. (Proven:
   the step's code_sketch executes fine.)
2. **Binds `seat`, not `result`.** The model's custom code bound named variables
   (`base`, `seat`, `backrest`) instead of `result`, so even past validation the build would
   have failed.

So the answer to "if we have the KB, why does grounding fail?" — it didn't. The model grounded
correctly; the GATES were wrong. Grounding belongs at EXECUTION (does the code build?), not at a
declared-manifest string match.

## The fixes (deterministic, tested on the model's exact plan)
1. **Forgiving operations check.** `validate_cadquery_operations` now accepts any operation in a
   real CadQuery namespace (`Workplane.*`, `Edge.*`, `Sketch.*`, `Solid.*`, ...), since the KB is
   a subset. Truly non-CadQuery names (`NotACadQueryClass.x`) are still rejected. The BUILD stage
   remains the real correctness gate.
2. **Forgiving result binding.** The custom runner now uses `result` if bound, else the last
   CadQuery object the code created (`base`/`seat`/...). The model's natural style just works.
3. **Deterministic alias normalization.** `rounded_box → filleted_box` (and the other known
   aliases) are remapped — type AND params — BEFORE validation, with NO LLM call. The single most
   common error costs zero repair cycles now.

Verified on the MODEL'S EXACT 15-step plan from your log: it now VALIDATES and BUILDS all 15 steps
(0.00s validate, ~15s build). Verify reports 8 disconnected components — which is HONEST: the
model positioned the chair parts with gaps so they don't fuse. That is a real geometry issue (the
verify-repair loop addresses it), not a false rejection.

## On the things I cannot do here (stated plainly)
- **I cannot run fast-rlm live in this sandbox.** Confirmed: Deno is NOT installed, and the LLM
  endpoints (Gemini, OpenRouter, OpenAI) all return HTTP 403 — the network blocks them. An API key
  does not change either fact. So I cannot exercise the live model (clarifier question quality,
  the agent's drafting). I CAN and DO run everything else: validation, normalization, build,
  verify, render, and the full orchestrator main() with the model stubbed.
- **Timing.** Your 23s was one Gemini call generating a ~14k-token plan — that's the model's
  latency, not the harness. The harness adds: build time (≈3s per custom step, because each runs
  in an isolated subprocess) and any repair cycles. My fixes REMOVE repair cycles for the common
  errors (relaxed gates + deterministic normalization → first-try validation), which is the main
  time lever I control. Batching all custom steps into one subprocess would cut build time further
  and is the clear next optimization.

## Honest remaining item
The chair builds but its parts don't all connect (8 components) because the model's positions
leave gaps. The verifier correctly flags this; the verify-repair loop feeds "8 components,
expected 1" back to fix positioning. Making the model position parts to touch (or explicitly
supporting multi-body assemblies) is a model-quality / contract choice, not a harness bug.

---

# Round 4 — empty code_sketch, build-failure crash, and the asking guarantee

## What broke and why
The model emitted a `custom` step whose `code_sketch` was an EMPTY string. Three gaps lined up:
1. **The schema accepted it** — `code_sketch: str` treats "" as valid, so post-validation passed.
2. **The build then failed** ("custom step has no code_sketch").
3. **Build failures CRASHED** (`sys.exit(1)`) — only VERIFY failures went through the repair loop,
   so a build failure had no recovery path.

## The real fixes (deterministic + tested on your exact plan)
1. **Schema rejects empty / non-CadQuery `code_sketch`.** A custom step with no real code is
   genuinely invalid; it is now caught at validation (cheap) and routed to the validation-repair
   loop. Verified on your exact plan: the empty step is rejected with a clear message.
2. **Unified repair loop.** Build failures AND verify failures now feed ONE bounded repair loop
   (re-plan with the specific error → re-validate → rebuild → re-verify). Nothing crashes
   mid-pipeline; exhaustion ends with a clean FAIL + trace. (Previously only verify failures
   recovered.)
3. **Asking is now GUARANTEED for vague prompts.** The clarifier still runs its focused model
   pass, but if the model returns no questions AND the prompt contains no dimensions/quantities at
   all (e.g. "design an office chair"), the orchestrator asks ONE consolidated question
   deterministically. So a vague request is never silently guessed — verified end to end.

## Current end-to-end flow
1. **Clarify** (orchestrator-owned): focused model pass for ≤3 critical questions; deterministic
   fallback asks one question if the prompt is under-specified. Answers injected as facts.
2. **Plan** (model in fast-rlm): drafts a GeometryPlan; should call validate_plan, but the
   orchestrator does not depend on it.
3. **Normalize** (deterministic): remap known invalid aliases (rounded_box → filleted_box) — no LLM.
4. **Validate** (orchestrator-owned, unconditional): real schema; on failure → bounded repair.
5. **Build** (kernel): primitives from fixed templates; custom code in an isolated subprocess
   (BREP transfer, timeout, forgiving about which variable holds the solid). On failure → repair.
6. **Verify** (fixed MeshLib battery = the verdict): watertight, one component, no self-intersection,
   positive volume, declared-vs-measured bbox. On FAIL → repair.
7. **Render** only after PASS. Custom output ships needs_review.

Every stage failure flows into the SAME bounded repair loop; the orchestrator owns correctness so
a non-compliant model degrades to a clean result, never a crash.

---

# Round 5 — fixing connectivity AT THE PLANNING LEVEL (mates + assembly)

## The real problem (your insight)
The planner *was* planning operations (the `operation` field + custom `code_sketch`), but it
positioned parts with ABSOLUTE coordinates it guessed — so "join" of two parts with a small gap
produced a valid-but-disconnected result (the 8-component chair). And the plan had no way to say
"this is one fused solid" vs "this is a multi-part assembly", so verify (hard-coded to expect 1
component) called every multi-part object a failure. You were right: fix it at the plan level.

## Layer 1 — assembly intent
- New plan field `assembly_kind: single_solid | assembly`.
- New step field `part` (assembly part name).
- `single_solid` → must be ONE connected component. `assembly` → folds within each part, keeps
  parts separate, and verify expects N parts (each checked for soundness). The planner now DECLARES
  the structure; the verifier honors it instead of guessing.

## Layer 2 (Option A) — relational placement (mates)
- New step field `attach: {to, at, my_anchor, gap}`. Instead of guessing `position`, a part mates
  to another part's anchor (top/bottom/left/right/front/back/center face centre). The kernel
  topologically resolves the attach graph (cycle-guarded) and DERIVES coordinates so parts touch by
  construction. `gap` controls spacing (0 = fused).
- Absolute `position`/`rotation` still works (radial patterns), and mixes freely with mates.

## Proven here (no LLM), in `tests/test_mates_and_assembly.py` (5/5)
- 3 mated boxes → ONE connected solid (no guessed coordinates).
- a 5 mm mate gap → correctly disconnected (2 components).
- a bolt-in-bracket assembly → declared 2 parts, verified as 2 components.
- an attach cycle → caught cleanly (no hang).
- **a full office chair built with mates → ONE connected solid (was 8 components).** Rendered: a
  proper chair, base + column + seat + backrest fused.

All six suites pass. The planner now plans *connections* ("seat attaches to column top"), which it
can reason about, instead of *coordinates*, which it guessed badly — and the geometry follows
deterministically.

## How the model learns this
`core.md` now instructs: prefer `attach` for parts that must connect; use `assembly_kind` +
`part` for genuinely separate pieces. The JSON output schema exposes `attach`, `part`, and
`assembly_kind`, so the model can emit them.
