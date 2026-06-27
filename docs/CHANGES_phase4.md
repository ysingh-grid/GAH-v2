# Phase 4 — reference-grounded design loop + test UI + custom hybrid

The previous phases made output **correct** (sound, coherent, right-sized) but it stayed **crude**:
the agent built plain-box chairs even with 39 primitives + shaping verbs, because the quality bar
("recognizable") accepted crude, and the agent had no concrete visual target to aim at. Phase 4
fixes both — without touching the fast-rlm engine.

## The core idea
Use the model's vision **host-side** (no engine fork): a user-provided REFERENCE IMAGE becomes (1)
a text **form brief** that guides the planner, and (2) the gold standard the **design-review critic**
judges the render against. Plus a minimal test UI to drive it, and an explicit hybrid policy for
when to use `custom`.

## What changed
- **A. Minimal test UI (`ui_server.py`, stdlib only).** Type a prompt + upload a reference image →
  clarifier questions shown in the page → answer → Run. The pipeline streams to the terminal; the
  page polls `/status` for the verdict + render/export paths. Testing-only (`python ui_server.py`).
- **B. Reference → form brief (`cad_kernel/fidelity.py: extract_design_brief`).** One host-side
  vision call turns the reference image into a structured BRIEF — per part: geometry approach
  (primitive vs loft/revolve/sweep), proportions, and especially exact **orientation** and
  connections. The orchestrator injects it into the planning task as a "REFERENCE FORM BRIEF" block.
  This attacks the *selection* and *orientation* problems at the source (the agent finally knows
  what to build and how parts are oriented). Fail-open (no brief if vision is unavailable).
- **C. Grounded design-review critic (`fidelity.critique`).** When a reference image is present
  (`FORGECAD_REFERENCE_IMAGE`), the critic sees BOTH the reference and the render and judges
  STRUCTURE / PROPORTION / ORIENTATION / REFINEMENT correspondence (form, not photo prettiness),
  rejecting crude/blocky/mis-oriented results with specific directives. With NO reference it falls
  back to the prior intent-only bar, so CLI runs and tests are unchanged. Token still mints only on
  geometry PASS + coherence + fidelity PASS. Fail-open + the `FORGECAD_FIDELITY_STUB` test hook kept.
- **D. Custom hybrid + gross-scale audit.** Skills/summary/task now state the HYBRID: primitives
  where exact dimensions/interfaces matter (holes, mating faces, structural sections); `custom`
  (KB-guided loft/revolve/sweep) for free-form aesthetic surfaces; and "you will be design-reviewed
  against the reference." Added a LENIENT per-custom `declared_dimensions`-vs-measured audit
  (`kernel._audit_custom_dims`, default 5x) that catches only blatant unit/scale blunders (e.g. code
  builds 400mm while declaring 40mm), surfaced as a clean build error. Custom still ships needs_review.
- **E. Model upgrade note.** `run.yaml` carries a comment to set the latest most-capable Gemini
  (one line; the same model powers the host-side brief + critic). NOT auto-changed — an invalid name
  would break every run; the user sets the verified current name.
- **F. Refactor + consistency.** `orchestrator.main()` split into a thin CLI `main()` and a reusable
  `run_pipeline(prompt, established_qa, reference_image_path)` (used by CLI and UI). `_fail` now
  raises `PipelineError` (no `sys.exit`) so it's safe in the long-lived UI process; the CLI/UI catch
  it. `generate_clarification_questions` extracted so the UI can show questions without asking.

## The honest custom-verification boundary (why custom is needs_review)
A custom solid that passes IS verified to be **sound** (positive volume, watertight, no
self-intersections), **coherent** (one connected object), and **looks like the request** (the vision
critic). What is NOT verified: **exact dimensions of features** (e.g. a 6.5mm hole vs 6.0mm — the
battery checks soundness, not feature sizes; the critic can't measure mm), **fine surface quality**,
and **functional/structural correctness**. Hence the hybrid rule (primitives for exact-dimension
features) and the needs_review tag. The 5x audit only closes the *gross scale* part of this gap.

## Determinism note
Geometry math, the build, and the fixed checks (sound/coherent/sized) remain **deterministic**. The
quality JUDGE (the design critic) is a **perceptual model** — grounded against a fixed reference to
make it as stable as possible, but it is, by nature, a judgment, not a bit-repeatable formula. That
is the unavoidable cost of "works for anything" + "high quality."

## Verified here (deterministic; vision stubbed/forced-unavailable)
`tests/test_reference_loop.py` (5/5): brief extraction via stub + fail-open; the grounded critic
reads the reference image and fails OPEN with no endpoint; no-reference falls back to the intent-only
bar; the per-custom audit fails a 10x-off custom and passes a correct/undeclared one; the
run_pipeline refactor is exposed. `ui_server.py` boots and serves the form + status (smoke-tested).
Full regression: **all 19 test files pass**. fast-rlm engine untouched.

## Needs the live machine
The end-to-end behaviour — whether the agent, given the reference brief and a strict grounded
critic, actually produces a refined, correctly-oriented chair — needs Deno + your key + a working
vision endpoint, and benefits from setting the latest Gemini model. The host-side substrate is proven
here; the live quality is the thing to observe on your machine (run `python ui_server.py`, give a
prompt + a chair reference image, and watch the terminal).
