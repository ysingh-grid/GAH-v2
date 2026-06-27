# Phase 0 — make the deterministic spine UNSKIPPABLE

v4/v5 built a real deterministic spine (fixed kernel + fixed verifier + schema). Phase 0
fixes the thing the live logs exposed: **at runtime the agent was bypassing that spine.**
In `logs/geometry_planning_2026-06-24T13-23-03-612Z.jsonl` the agent FINAL'd a chair plan
having called ZERO of `validate_plan` / `build_verify_render` / `get_primitives_library` —
the entire in-loop "prove it sound yourself" contract never fired. It was rescued only by
the orchestrator's post-FINAL gate, which then fails the whole run with nothing gained from
the loop. The same run also ran `import cadquery` in the WASM REPL (crash) and silently
downgraded a freeform backrest to a box to recover.

Phase 0 makes verification structurally unavoidable, clarifies the tool/code boundary, and
gives the loop deterministic feedback — all in the Python/MCP/skills layer. The bundled
fast-rlm TS engine was NOT touched.

## 1. Unforgeable verification token — the real fix for "the agent skips verify"
Prompt threats ("you are FORBIDDEN from FINAL without a PASS") demonstrably do not change
behaviour. So the contract is now enforced structurally:

- `cad_kernel/attestation.py` (new): `canonical_plan_hash` (canonical JSON of the plan
  EXCLUDING the token field), `make_token` (HMAC-SHA256 of `hash + ":PASS"` under a per-run
  secret), `verify_token` (constant-time).
- `cad_kernel/geometry_server.py`: on a genuine `verdict=="PASS"`, `build_verify_render`
  returns `verification_token`. No PASS → no token.
- `orchestrator.py`: generates a per-run `run_secret`, injects it ONLY into the
  `geometry_kernel` MCP server's `env` (never into the REPL `env_variables`, so the model
  cannot read it); adds `verification_token` as a REQUIRED field of the output schema; and at
  the post-FINAL gate pops the token and `verify_token`s it against the FINAL'd plan BEFORE
  anything else — rejecting missing / forged / altered-plan tokens loud.

Enforcement split (intentional, stated honestly): the fast-rlm output schema (Ajv) can only
force the token to be PRESENT at FINAL — it cannot run an HMAC. AUTHENTICITY is enforced by
the orchestrator gate. Presence (in-loop driver) + authenticity (at the gate) means the only
practical way to complete a run is a genuine `build_verify_render` PASS for that exact plan.
The token is bound to the plan hash (excluding itself), so embedding it does not change the
hash, and a valid token proves THAT EXACT plan passed. Forging a valid HMAC without the
secret is cryptographically infeasible; a fabricated token simply discards the run.

Remove-it test: delete the token and an agent can again FINAL an unbuilt plan — a real
failure. It passes.

## 2. Tool/code boundary (stops the `import cadquery` crash + silent downgrade)
`import cadquery` cannot work in the pure-WASM REPL; the host kernel is the only executor.
`skills/core.md` and the orchestrator task now state plainly: you author a plan DICT, you do
NOT run CAD here, `import cadquery` will fail, and a `custom` step's `code_sketch` is TEXT the
host runs — not code you run. (Under the no-engine-edit constraint this is the available
lever; a REPL-level stub module would require an engine change, deferred.)

## 3. Attempt ledger — deterministic, escalating feedback
`geometry_server.py` keeps an in-process ledger (the server is spawned once per run and
persists across calls). Every `build_verify_render` returns `next_action`: a first/new
failure says "fix the cited cause"; the SAME check failing across attempts escalates to
"NO-PROGRESS — change strategy or FINAL the best sound candidate"; re-submitting an IDENTICAL
failing plan is flagged as the forbidden move; PASS says "embed the token and FINAL". This
moves no-progress/escalation logic out of fragile prompt prose into the tool itself, so
failures bubble usefully.

## 4. Single source of truth for the primitive library
The primitive library was duplicated in three places (`schemas/primitives.json`, an inlined
489-line dict in `tools/get_primitives.py`, and the host MCP reader). The native
`get_primitives_library()` now reads `PRIMITIVES_JSON_DATA` (injected into the REPL by the
orchestrator via `env_variables`), and the inlined dict is deleted (489 → 26 lines).
`schemas/primitives.json` is now the only source, shared by the native tool, the host MCP
tool, and the Pydantic schema — they can no longer drift.

## Verified here (deterministically, no live LLM)
`tests/test_phase0_token_gate.py` (6/6): a genuine PASS mints an authentic token; the gate
ACCEPTS a verified token-carrying FINAL (and strips the token before pydantic/plan_store);
the gate REJECTS a tokenless FINAL (the exact observed failure), a forged token, and a
real token on a post-verification-altered plan; FAIL yields no token and an identical
resubmission escalates in the ledger; native tool == primitives.json == schema registry with
no inlined dict.

Full regression: all existing suites pass unchanged — `test_cad_pipeline`, `test_host_mcp`,
`test_mates_and_assembly`, `test_planning_substrate`, `test_union_tol`, `test_v5_capabilities`,
`test_validation_and_placement`, `test_validation_boundaries`, and (run with repo root on
PYTHONPATH) `test_base`, `test_chair`, `test_chair_parts`, `test_gear`, `test_microshift`,
`test_validate`, `test_validate_exact`.

## Needs your machine (Deno + RLM_MODEL_API_KEY + cadquery/meshlib venv)
The live agent loop. Phase 0's host-side guarantees (token mint/verify, gate rejection,
ledger escalation, single source of truth, schema requirement) are all proven here with the
model stubbed; what your machine adds is confirming the live agent, now unable to FINAL
without a real token, actually drives the build/verify loop to convergence.

## Explicitly NOT in Phase 0 (deferred)
Visual / "Thinking in 3D" critique (Phase 1); the promotion flywheel for generality /
patterns-vs-KB (Phase 2); Temporal + eval flywheel + ForgeCAD surface (Phase 3).
