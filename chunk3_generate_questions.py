"""
CHUNK 3 — generate_clarification_questions()
================================================================================
Generates ≤3 questions using a SEPARATE mini model call (depth=0).
This is the "thinking" half — it does NOT ask the user. Fail-safe → returns [].

Place this function in your orchestrator.py, below Chunk 2.
It requires: CLARIFIER_ROLE (from Chunk 2) and your RLM runner.

WHAT YOU MUST ADAPT:
  - Replace `fast_rlm.run(...)` with YOUR agent runner's equivalent.
    The call pattern is: single-turn, output_schema={...}, depth=0, no tools.
    If your runner uses a different API, adapt the args.
  - The `user_prompt` string and `q_schema` dict are universal — no changes.
    The schema just needs to produce {"questions": ["q1","q2","q3"]}.
  - The safety-net question (no-numbers fallback) — feel free to rewrite
    if your domain isn't CAD. Add/remove topics.
================================================================================
"""

def generate_clarification_questions(user_prompt, config, llm_kwargs, flags):
    """
    Generate up to 3 critical clarifying questions for a request.
    (The question-generation half of clarification, with no asking.)
    Reused by the CLI clarifier AND the test UI. Fail-safe -> [].
    """
    if not flags.get("clarify", True):
        return []

    questions = []
    try:
        q_schema = {
            "type": "object",
            "properties": {"questions": {"type": "array", "items": {"type": "string"}}},
            "required": ["questions"],
        }
        clar_cfg = dict(config or {})
        clar_cfg["max_depth"] = 0   # <-- single call, no recursion

        # ---- ADAPT THIS: replace fast_rlm.run with YOUR RLM runner ----
        res = fast_rlm.run(
            query={
                "role_instructions": CLARIFIER_ROLE,          # from Chunk 2
                "task_instructions": f"Design request: '{user_prompt}'.",
            },
            prefix="clarifier",
            config=clar_cfg,
            llm_kwargs=llm_kwargs or None,
            output_schema=q_schema,
            verbose=False,
        )
        # ---- end ADAPT ----

        questions = ((res.get("results") or {}).get("questions") or [])[:3]
    except Exception as e:
        print(f"[clarify] question pass skipped ({e}); planning will proceed without it.")
        questions = []

    # Safety net: if the prompt has NO numbers and the model returned no
    # questions, ask ONE consolidated question so we don't blindly guess.
    import re as _re
    if not questions and not _re.search(r"\d", user_prompt or ""):
        questions = [
            "This request doesn't specify key parameters. What should I design to — "
            "overall size (mm), load/weight capacity, material, and any required "
            "features? (reply with specifics, or 'use sensible defaults')"
        ]
        print("[clarify] prompt is under-specified — asking one consolidated question.")

    return [q.strip() for q in questions if (q or "").strip()]
