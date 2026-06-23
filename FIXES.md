# Fixes from the office-chair run (general, not case-specific)

## 1. Invented primitive types (`rounded_box`) — root cause + general fix
The model guessed a primitive that does not exist; the discriminated union rejected
it only AFTER FINAL. The deeper problem: **the model had no way to validate in-loop.**
The skill told it to run `GeometryPlan(**plan)` in the REPL, but that is impossible —
the WASM sandbox has no `primitives.json`, so the schema's primitive union is empty and
would reject everything.

Fix — a host validation oracle: **`validate_plan(plan)`** (new MCP tool on `host_tools`).
It runs the REAL CPython schema (the same check that runs after FINAL) and returns
`{valid, errors:[{location,message}], valid_primitive_types}`. The skill now requires the
model to call it before FINAL, fix the reported errors, and only FINAL when `valid=True`.
This is general: it catches invented types, extra/missing params, short rationales — any
schema violation — and hands back the list of valid primitive types so the model
self-corrects (`rounded_box` → `filleted_box` or a `custom` step).

## 2. `ask_user` never fires — general fix
The agent went straight to FINAL without a gap ledger or any question. Cause: the ledger
was only *described*, never *required*. Fix — an enforced **two-turn gate** in the task
instructions: TURN 1 may ONLY print the GAP LEDGER (each unknown marked BENIGN+default or
CRITICAL+reason) and call `ask_user` for every CRITICAL row — **FINAL is forbidden in turn
1**. TURN 2 builds, validates via `validate_plan`, and FINALs. This forces the unknowns to
be externalized and the genuinely critical ones asked, without forcing a pointless question
on a fully-specified request.

## 3. Placement convention — general fix
The chair legs all carried `position:[180,0,25]` + a per-leg `rotation`, but the kernel
rotated about the origin FIRST then translated in world coords, so every leg stacked in one
place. Fixed `kernel._place` to a single clear convention, now stated in the skill:
**apply `position` first (translate in the part's local frame), THEN `rotation` about the
global origin (X,Y,Z).** A radial pattern = translate out along +X by the radius, then
`rotation=[0,0,angle]` per copy. Verified: a 5-star base now splays into a star and stays
one connected solid.

## How tools and skills reach the model (verified against a real run + the live server)
- **role_instructions** = `skills/core.md` (the thin router: conventions, the gap-ledger
  gate, the primitive-type rule, the placement convention, the validate-then-FINAL loop)
  + the compact primitives summary. Always present.
- **task_instructions** = the two-turn gate + hard rules, with the user's prompt.
- **Native tool (1)** — `get_primitives_library()` — self-contained (returns an inline
  dict), so it works inside the WASM REPL.
- **MCP tools (9) on `host_tools`** — `read_workspace_file, ask_user, load_skill,
  validate_plan, get_primitives_library, cadquery_browse, cadquery_search, cadquery_doc,
  cadquery_example`.
- **Progressive skills** — the detailed `freeform` procedure is NOT in the base prompt; the
  model fetches it via `load_skill(topic="freeform")` only when no primitive fits.
- **output schema** — the JSON Schema carries `name/operation/position/rotation`; it is now
  reconciled with the Pydantic model, so those fields are accepted, not rejected.

## Verified here (no LLM): `tests/test_validation_and_placement.py` (9/9)
- `validate_plan` accepts valid primitive/custom plans; rejects `rounded_box`, extra params,
  short rationale; offers `filleted_box` as the real alternative.
- the radial 5-star base validates, builds, splays (bbox > 500 mm in X and Y), and is one
  connected solid.
All previous suites still pass (`test_planning_substrate`, `test_cad_pipeline`,
`test_host_mcp`, `test_validation_boundaries`).

## Runs on your machine (Deno + key)
The live RLM planning. The substrate it depends on — the validation oracle, the gap-ledger
gate wiring, the placement convention, the tool/skill plumbing — is verified here.
