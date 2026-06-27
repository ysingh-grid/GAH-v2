# Phase 2 — build → verify → render, MeshLib KB, and planning fixes

Two things landed: (A) planning polish — make `ask_user` fire, reconcile the schema,
and load skills progressively; (B) a deterministic build → verify → render stage with
a fixed MeshLib verification battery and a curated MeshLib KB.

## A. Planning fixes

**`ask_user` now fires by design.** The agent was assuming everything (confirmed: 0
real `ask_user` calls in the latest run). The cause was instructions that only ever
discouraged asking. The new `skills/core.md` forces a **Gap Ledger** in Step 1: the
model must list every unknown, mark each BENIGN (→ assumption) or CRITICAL (→ ask),
with a reason. Asking now follows mechanically from the ledger instead of being a vibe.

**Schema reconciled.** The minimized JSON schema sent to the model carried `name` and
`operation`, which the strict Pydantic steps (`extra="forbid"`) rejected — silent
post-FINAL rejections. `name`, `operation`, **`position`**, and **`rotation`** are now
real fields on every step (primitive and custom). They also give the build stage the
placement + boolean info it needs, so a validated plan now builds directly.

**Progressive skill loading.** `core.md` is a thin always-on router (identity, the core
loop, the gap ledger, a skill index). Detailed skills load on demand via the new
`load_skill(topic)` MCP tool — `freeform` (CadQuery-KB planning) is fetched only when no
primitive fits, not dumped into every prompt. Same retrieval pattern as the KBs.

## B. Build → verify → render

`cad_kernel/` runs the native stack the WASM REPL cannot:

- **`kernel.py`** — executes a `GeometryPlan` deterministically: primitive steps from the
  FIXED `primitives.json` templates, custom steps from their `code_sketch`, placed by
  `position`/`rotation` and combined by `operation`. Same plan in → same solid out. Returns
  a per-step status so a repair loop knows exactly which step failed.
- **`verify.py`** — the FIXED MeshLib battery (the VERDICT): positive volume, watertight,
  expected component count, no self-intersections, and measured-vs-declared bounding box.
  Authored by a human, run identically every time. The RLM cannot choose or skip it; it may
  only `run_advisory(...)` extra checks that flag concerns and never affect the verdict.
- **`render.py`** — headless, GPU-free multi-view PNG (matplotlib). Runs after verify.
- **`geometry_server.py`** — host MCP server exposing `build_plan`, `verify_solid`,
  `render_solid`, `build_verify_render`, `run_advisory`, and the MeshLib KB tools.

**Why fixed checks, not RLM-chosen:** if the model that generated the geometry also picks
how it is graded, it passes its own mistakes (the bug and the blind spot share a cause). A
fixed battery cannot be steered around the very error that would catch it. A passing verdict
means SOUND + RIGHT-SIZED, not "the right object" — freeform stays `needs_review`.

## C. MeshLib KB (`meshlib_kb_pack/`)

MeshLib's Python API is compiled (pybind11), so the KB is built by **introspection**
(`scripts/build_meshlib_kb.py`) — signatures + docstrings — and **curated** to the
verification-relevant subset (121 entries from ~2766 symbols). Note: meshlib.io docs are
Doxygen/C++, which is the wrong surface for Python calls, so introspection is the right
source. Tools: `meshlib_browse / meshlib_search / meshlib_doc`. Its job is to ground the
fixed battery you author and the advisory checks the RLM proposes — never to let the RLM
choose the verdict.

## What is proven here vs. on your machine
- **Verified deterministically (here):** `tests/test_cad_pipeline.py` builds + verifies +
  renders a primitive bracket and a freeform revolved solid (both PASS), and the battery
  CATCHES a disconnected 2-component solid and a wrong-size part, each with a `localized_fix`.
  `tests/test_planning_substrate.py` and `tests/test_host_mcp.py` still pass.
- **Runs on your machine (Deno + key):** the live RLM planning. The substrate it feeds is proven.

## Known limitation (honest)
`kernel.py` targets single-solid parts. Multiple `"new"` bodies collapse via `.val()`; true
multi-body assemblies need `.vals()`/compound handling — a clean next step, not wired yet.

## Run
```bash
# build-server env (native): pip install cadquery meshlib matplotlib trimesh mcp
python tests/test_cad_pipeline.py          # build -> verify -> render (no LLM)
python cad_kernel/geometry_server.py       # the MCP build/verify/render server
# planning env: python orchestrator.py     # needs Deno + RLM_MODEL_API_KEY
```
