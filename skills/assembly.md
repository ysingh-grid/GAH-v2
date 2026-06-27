# SKILL: recursive decomposition of a large assembly (loaded on demand)

Use this ONLY when a design is too large to reason about as a single plan (many distinct
parts, each non-trivial). For anything a single plan can handle, do NOT recurse — the flat
stateful loop in core.md is faster and simpler.

## The tree
You (the root) are the assembler. Each child owns ONE part and proves it sound on its own.

1. **Decompose into parts.** Identify the major parts (e.g. chair: seat, back, column, base,
   casters). For each, write a short spec: what it is, its key dimensions, and how it connects
   to the others (which face mates to which).

2. **Spawn one child per part — pass tools + MCP EXPLICITLY.** Sub-agents inherit nothing, so
   every call must re-pass the geometry tools and servers:

   ```repl
   seat = await llm_query(
       {"part": "seat", "spec": seat_spec},
       instruction=("Build ONLY this part. Draft a GeometryPlan for it, validate_plan it, then "
                    "build_verify_render it (expected_components=1) until verdict==PASS. Return "
                    "the validated plan dict via FINAL. Do not build the rest of the assembly."),
       tools=[get_primitives_library],
       mcp=["host_tools", "geometry_kernel"],
       schema={"type": "object"},
   )
   ```

   Run independent parts in PARALLEL for speed:
   ```repl
   seat, back, base = await batch_llm_query(
       llm_query(seat_task,  instruction=..., tools=[...], mcp=["host_tools","geometry_kernel"]),
       llm_query(back_task,  instruction=..., tools=[...], mcp=["host_tools","geometry_kernel"]),
       llm_query(base_task,  instruction=..., tools=[...], mcp=["host_tools","geometry_kernel"]),
   )
   ```

3. **Assemble the sub-plans — let the kernel do the bookkeeping.** Call `merge_subplans`; it
   namespaces names, rewires intra-part mates, renumbers `sequence_id`, tags parts, and applies
   your cross-part connections deterministically. You only describe WHICH parts connect and HOW:

   ```repl
   merged = await mcp_call("host_tools", "merge_subplans",
       parts=[{"name": "post", "plan": post}, {"name": "cap", "plan": cap}],
       connections=[{"from": "cap", "to": "post", "at": "top"}],   # cap's seed mates onto post's top
       assembly_kind="single_solid", title="capped post")
   ```
   In `connections`, a bare `"post"` means that part's seed (first) step; use `"post.plate"` to
   target a specific step. `at`/`my_anchor` accept the full anchor grammar (faces, edges,
   corners), plus `gap` and `offset`. Do NOT renumber or rewire by hand — that is exactly the
   error-prone bookkeeping `merge_subplans` exists to remove.

4. **Verify the WHOLE.** Run `build_verify_render` on the merged plan with the correct
   `expected_components` (1 for a fused single_solid; the part count for a separate-parts
   assembly). If the whole fails where the parts passed, the fault is in the INTER-part mates —
   fix the `attach` between parts, not the parts themselves.

5. **FINAL the merged, verified plan.**

## Stopping inside the tree
- Depth is bounded by `max_depth` — children at the leaf cannot recurse further (the engine
  forbids it), so the tree cannot run away.
- Each child self-governs with the same termination contract as core.md (success / budget /
  no-progress / impossible).
- The whole run is bounded by `max_global_calls` (root + all children). If you are nearing it,
  stop spawning and assemble the parts you already have.

## Don't
- Don't pass the whole assembly context to each child — pass only that part's spec (compression).
- Don't let a child build a neighbouring part "to be safe" — that breaks component counting.
- Don't reference integer sequence_ids across parts; use names for cross-part `attach`.
