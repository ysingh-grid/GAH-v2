# ForgeCAD v4 — what changed and why

v4 turns the RLM from a constrained single-shot JSON generator (v3) into a **stateful
reasoning agent with a deterministic spine**. The agent now drafts a plan AND drives its
own build -> verify loop in one REPL session, against the real host geometry kernel.

## Removed (the bandages)
- **Three host-side stateless repair loops** in `orchestrator.py` (`_run_repair`, the
  schema-validation `while`, the `vrepair` loop). Each was a fresh, memoryless `fast_rlm.run()`
  that re-parsed the prior plan out of a prompt string and fixed one thing blind. Replaced by
  the agent's in-REPL loop, which keeps full state and sees the real verdict.
- **`normalize_aliases` / `_CONFUSABLE_PAIRS` / `_ALIAS_PARAM_MAP`** host auto-remap. The agent
  now fixes an invented primitive itself from `validate_plan`'s `errors` + `valid_primitive_types`.
  The confusable list survives only as a PROMPT HINT (no silent host rewrite).
- **Host bbox auto-sync.** The agent reconciles declared vs measured dimensions in-loop.
- **The `"do not call llm_query"` prohibition.** Scoped recursion is now allowed (skills/assembly.md).
- **`max_repair_attempts` / `max_validation_repair_attempts`** in run.yaml. There is no host-side
  retry count anymore.

## Added / fixed
- **`geometry_kernel` MCP server is now WIRED** into the planning run (it existed in v3 as
  `cad_kernel/geometry_server.py` but was never connected). The agent calls
  `build_verify_render` and gets the real verdict; the heavy solid stays host-side, only the
  id + JSON report cross back.
- **Stateful build->verify loop** + a **layered termination contract** in `skills/core.md`
  (success / budget / no-progress / impossible). Stopping is governed by fast-rlm's native
  budgets, not a fixed count.
- **Recursive decomposition** for large assemblies in `skills/assembly.md` (one child per part;
  tools + `mcp=[...]` re-passed explicitly because sub-agents inherit nothing).
- **Bug fix:** `tools/host_mcp.py` `load_skill` referenced an undefined `_SKILLS` — it would
  raise `NameError`, so the freeform path the prompt advertised was dead. `_SKILLS` is now defined.
- **`orchestrator.py` is now a thin gate**: set up -> ONE stateful agent run -> ONE authoritative
  host build+verify (the same fixed battery) -> render/export. On failure it fails LOUD with the
  trace; it never silently repairs.

## Deliberately KEPT (not bandages — the integrity of the system)
- The **fixed verification battery** (`cad_kernel/verify.py`) stays deterministic and unskippable.
  The generator never grades itself. The KB makes the model able to reason about *what to build*;
  it does not make the model trustworthy to certify *that it succeeded*.
- The **deterministic kernel** (primitives from templates, mate resolution) and the
  **GeometryPlan schema** (the data contract) are unchanged.
- Custom-step subprocess isolation + timeout; the clarifier pass.

## Ceiling to remember
A PASS means SOUND + RIGHT-SIZED, not "the right object". Complex freeform geometry can be
*built and verified for soundness* but ships at `needs_review` — semantic correctness is not
certifiable here. The relational `attach` vocabulary is the six planar faces + center; genuinely
complex relational placement (angled bosses, curved-face mates) still needs custom code or an
expanded anchor algebra.

## What needs your machine (Deno + cadquery/meshlib venv + API key)
Live convergence of the agent loop and the quality of generated plans. The substrate — the
wiring, the stateful loop contract, the deterministic kernel/verifier, the schema — is here and
syntax-checked. Run `orchestrator.py` from the project venv (so the spawned MCP servers have
cadquery + meshlib + mcp).
