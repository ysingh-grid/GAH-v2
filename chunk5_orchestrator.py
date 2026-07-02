"""
CHUNK 5 — ORCHESTRATOR INTEGRATION (3 sub-parts: main, run_pipeline, task_instructions)
================================================================================
This is the critical integration code. It shows EXACTLY how the pre-RLM
clarifier connects into your main orchestrator. THREE places to integrate:

  PART A — main(): call gather_clarifications() BEFORE run_pipeline()
  PART B — run_pipeline(): inject established_qa as IMMUTABLE FACTS into
           task_instructions AND into the final plan dict AFTER the token gate
  PART C — generate_task_instructions(): stitch established_block into the prompt

THE GOLDEN RULE:
  gather_clarifications() runs → established_qa is born →
  run_pipeline() receives established_qa →
    - injects it into the RLM's task_instructions as given facts
    - injects it into plan_dict["clarifications"] AFTER the token gate
================================================================================

---- PART A: main() — the entry point ----

def main():
    \"\"\"CLI entry: clarify in the terminal, then run the pipeline.\"\"\"
    config, llm_kwargs, flags = load_run_config()          # your config loader
    print(\"\\n--- Your App ---\")
    user_prompt = input(\"Enter your request: \")

    # ---- THE KEY LINE: gather clarifications BEFORE the RLM ----
    established_qa = gather_clarifications(user_prompt, config, llm_kwargs, flags)
    # established_qa is now: [{\"question\": \"...\", \"answer\": \"...\"}, ...]
    #                          OR [] if clarify is disabled or failed.

    try:
        result = run_pipeline(user_prompt, established_qa)
    except PipelineError:
        sys.exit(1)
    sys.exit(0 if result.get(\"ok\") else 1)


---- PART B: run_pipeline() — two injection points ----

def run_pipeline(user_prompt, established_qa, reference_image_path=None):
    \"\"\"
    Run the full stateful pipeline for a prompt + already-gathered clarifier
    answers. Returns a result dict on success; raises on honest failure.
    \"\"\"

    # === INJECTION POINT 1 (BEFORE the RLM launches): build task_instructions ===
    established_block = \"\"
    if established_qa:
        facts = \"\\n\".join(
            f\"  - {c['question']} -> {c['answer']}\" for c in established_qa
        )
        established_block = (
            \"These requirements were ALREADY clarified with the user; \"
            \"treat them as given facts:\\n\" + facts
        )

    payload = {
        \"role_instructions\": skill_content,   # your role/skill text
        \"task_instructions\": generate_task_instructions(
            user_prompt, established_block,     # <--- IMMUTABLE FACTS injected here
            reference_block, edit_block,        #     (remove these if you don't need them)
        ),
    }

    # ... assemble config, schema, tools, MCP servers ...

    # Optionally pass clarifications to the geometry/env as immutable intent.
    # This makes host-side critics judge against the USER's words, not the agent's.
    # geom_env[\"YOUR_INTENT_KEY\"] = json.dumps({
    #     \"prompt\": user_prompt, \"clarifications\": established_qa,
    # })

    # ---- LAUNCH THE RLM ----
    result = fast_rlm.run(
        query=payload, prefix=prefix, config=config,
        llm_kwargs=llm_kwargs, output_schema=schema,
        tools=tools, mcp_servers=mcp_servers,
        env_variables=repl_env_variables,
        verbose=flags.get(\"verbose\", True),
    )

    plan_dict = result.get(\"results\")

    # ... token gate, authoritative build/verify ...

    # === INJECTION POINT 2 (AFTER the token gate): record clarifications ===
    # Clarifications are non-geometric and must NOT affect token authentication.
    # Inject them AFTER the token is verified.
    if established_qa:
        plan_dict[\"clarifications\"] = established_qa

    # ... export, render, save ...

    return {\"ok\": True, \"plan\": plan_dict, ...}


---- PART C: generate_task_instructions() — stitch established_block in ----

def generate_task_instructions(user_prompt, established_block,
                               reference_block=\"\", edit_block=\"\"):
    \"\"\"Build the full task prompt. established_block goes in the VARIABLE
    section (run-specific), AFTER static rules but BEFORE the run request.\"\"\"
    static = [
        # ... your static role instructions / rules ...
    ]
    variable = [
        f\"The user wants to design: '{user_prompt}'.\",
        established_block,      # <--- IMMUTABLE FACTS (empty string if no clarifications)
        reference_block,        # <--- optional reference image / form brief
        edit_block,             # <--- optional edit mode
    ]
    return \"\\n\".join(static + variable)


# ------------ WHAT YOU MUST ADAPT (Chunk 5) ------------
# - `load_run_config()` — your own config loader.
# - `fast_rlm.run(...)` — your own RLM/agent runner. The important thing is:
#   the `query` dict passed to it MUST contain `established_block` inside
#   `task_instructions`.
# - `generate_task_instructions()` — your own prompt assembler. The critical
#   rule: established_block goes in the VARIABLE section (the run-specific part).
# - `PipelineError` — your own failure exception class (or use a plain Exception).
# - The `plan_dict[\"clarifications\"]` injection: adapt the key name to whatever
#   your plan schema uses (or add a new key).
# - The `reference_image_path` / `reference_block` / `edit_block` are optional
#   extras from this codebase; remove them if you don't need them.
# ------------
