"""
CHUNK 4 — gather_clarifications() — THE MAIN ENTRY POINT
================================================================================
Ties Chunks 1+2+3 together:
  generate_clarification_questions() → ask_user_impl() for each → return Q&A list.
Fail-safe: any problem → returns [] (planning proceeds without clarification).

Place this function in your orchestrator.py, below Chunk 3.

WHAT YOU MUST ADAPT:
  - The import path: `from tools.clarify_io import ask_user_impl`
    Change this to wherever you placed Chunk 1.
  - `generate_clarification_questions` and `_normalize_clarification_answer`
    must be importable (same module or imported).
  - The `flags` dict key "clarify" controls whether this runs at all;
    put it in your config/yaml or hardcode.
================================================================================
"""

def gather_clarifications(user_prompt, config, llm_kwargs, flags):
    """
    Dedicated pre-planning pass:
      1. Generate ≤3 critical questions (Chunk 3).
      2. ASK the user each question (Chunk 1).
      3. Return real Q&A list [{question, answer}, ...].
    Single-purpose model call (depth 0). Fail-safe: any problem -> [].
    """
    if not flags.get("clarify", True):
        return []

    # Import the robust ask implementation (Chunk 1)
    try:
        from tools.clarify_io import ask_user_impl
    except Exception as e:
        print(f"[clarify] disabled (io import failed: {e})")
        return []

    # Generate questions (Chunk 3)
    questions = generate_clarification_questions(user_prompt, config, llm_kwargs, flags)

    qa = []
    for q in questions:
        q = (q or "").strip()
        if not q:
            continue
        print(f"[clarify] asking: {q}")
        ans = ask_user_impl(q)
        if ans and not ans.startswith("[UNANSWERED"):
            norm = _normalize_clarification_answer(ans)  # from Chunk 2
            if norm:
                qa.append({"question": q, "answer": norm})

    if qa:
        print(f"[clarify] gathered {len(qa)} answer(s) from the user.")
    return qa
