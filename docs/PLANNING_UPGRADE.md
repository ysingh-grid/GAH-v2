# Planning stage upgrade — primitives + CadQuery freeform fallback

This extends the **planning** stage so the RLM can plan **any** shape: primitive-backed
when a primitive fits, and a freeform CadQuery plan (via the KB) when none does — with
the flow driven by the RLM's reasoning instead of a hard-coded turn script.

## What changed (and why)

**`schemas/geometry_plan.py`** — added a first-class freeform step.
- New `CustomStep` (`primitive_type: "custom"`) carrying `shape_description`,
  `cadquery_operations` (ids from the KB), `code_sketch`, `declared_dimensions`, and a
  fixed `trust_tier: "needs_review"`. Added to the discriminated union, so a plan can now
  mix primitive steps and freeform steps.
- `clarifications` is no longer forced (`min_length` removed) — the RLM asks only when
  genuinely ambiguous; empty is valid.
- Auto-set `contains_freeform` flag (True ⇒ the plan ships needs_review).
- Removed the hard-coded `/Users/...` path (env `PRIMITIVES_JSON` override instead).

**`tools/host_mcp.py`** — wired the CadQuery KB onto the host server and hardened clarify.
- Registers `cadquery_browse / cadquery_search / cadquery_doc / cadquery_example` from
  `cadquery_kb_pack/` (523 ops + 33 worked examples) — the freeform vocabulary.
- Added a host-side `get_primitives_library` (the in-REPL one can't read host files from WASM).
- `ask_user` is now robust: env auto-answer → macOS dialog → `/dev/tty` → safe default.
  It never crashes the run.

**`skills/core.md`** — rewrote as a decision procedure, not a script.
- Prefer primitives; fall to the CadQuery KB freeform path when no primitive fits
  (search → doc the exact signatures → example → emit a `custom` step, needs_review).
- Clarify only on genuine ambiguity.

**`orchestrator.py`** — de-hardcoded the task instructions (goal + tools + procedure; the
RLM chooses its own turns) and updated the injected primitives guide to mention the
freeform fallback.

## The flow now
intent → (clarify only if genuinely ambiguous) → decompose → per feature: primitive if one
fits, else freeform CadQuery plan from the KB → assemble in build order → validate against
`GeometryPlan` in the REPL → `FINAL`. Plans with any freeform step are flagged
`contains_freeform=True` (needs_review).

## Run it
```bash
# host server deps (the env that runs tools/host_mcp.py):  pip install mcp
# rlm side: Deno 2+ on PATH, RLM_MODEL_API_KEY in .env
python orchestrator.py            # interactive planning run
```

## Tests (no LLM / API needed — run anywhere)
```bash
pip install mcp pydantic
python tests/test_planning_substrate.py   # 13 hard prompts + schema representation
python tests/test_host_mcp.py             # spawns the host server, checks all tools
```

## Verified here vs. on your machine
- **Verified deterministically (here):** schema represents primitive/freeform/hybrid plans;
  the KB retrieves correct ops for every hard prompt (gear→polygon/extrude, bolt→sweep/helix,
  handle→loft, wine glass→revolve, planetary→makeHelix); the host MCP server exposes all
  tools and answers; everything compiles.
- **Runs on your machine (needs Deno + key):** the live RLM reasoning — decomposition,
  clarifying questions, and writing the actual plan. The substrate it depends on is proven.

## One honest note
A freeform `custom` step is a *plan*, not a built solid. It is always `needs_review`:
the later build/verify stage can confirm it is a sound, right-sized solid, but cannot
certify it is "the right object". Recurring freeform shapes are your promotion candidates
for new primitives.
