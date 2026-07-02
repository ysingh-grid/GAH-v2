"""
CHUNK 2 — Clarifier constants + helpers
================================================================================
These go in your orchestrator.py (or whatever your main entrypoint is).
Place them at module level, near the top, after imports.

WHAT YOU MUST ADAPT:
  - CLARIFIER_ROLE: If your domain is NOT CAD/geometry, rewrite the "ONLY about"
    list to match YOUR domain's non-negotiable facts (e.g. for code generation:
    language version, framework, deployment target, etc.).
  - The rest (_VAGUE_ANSWER_RE, _normalize_clarification_answer) needs NO changes.
================================================================================
"""

import re as _re_clar

# (A) The role instructions for the dedicated clarifier model call.
#     This makes it ask ONLY about non-negotiable facts (size, count, orientation,
#     material) in plain, everyday language — never jargon.
CLARIFIER_ROLE = (
    "You help ANY user — technical or not — pin down only the few NON-NEGOTIABLE facts needed to "
    "model their object, where a wrong guess would force a redesign. Ask AT MOST 3 short questions, "
    "ONLY about: (1) overall SIZE or the space it must fit in; (2) the COUNT of the main repeated "
    "feature if it matters (e.g. number of blades/legs/shelves); (3) any critical ORIENTATION or "
    "how/where it MOUNTS or connects; (4) MATERIAL only if it changes the shape. Skip anything with "
    "a safe standard default. RULES for each question: use PLAIN, everyday language (NO jargon like "
    "'IP rating', 'load path', 'bolt PCD' — if such a concept matters, explain it in simple words); "
    "give 2-4 concrete EXAMPLE answers in parentheses so a non-expert can just pick one; and always "
    "end with an escape like \"(or say 'use standard defaults' / 'not sure')\". Example size "
    "question: \"About how big should it be? (fits in your hand ~10 cm / desktop ~30-50 cm / "
    "furniture-sized ~1 m, or give a number in mm; or say 'use standard defaults')\". Output STRICT "
    'JSON: {"questions": ["...", "..."]} with at most 3 questions, or {"questions": []} if the '
    "request already specifies everything important. Ask nothing else."
)

# (B) Regex for detecting vague/non-answers ("idk", "standard", "not sure"...)
#     These are normalized to a canonical string so downstream logic is deterministic.
_VAGUE_ANSWER_RE = _re_clar.compile(
    r"^(?:idk|i\s*don'?t\s*know|not\s*sure|dunno|no\s*idea|any(?:thing)?|whatever|"
    r"standard|sensible|defaults?|use\s+(?:standard|sensible|your)\s+\w+|you\s+(?:decide|choose)|n/?a|-)$",
    _re_clar.IGNORECASE,
)


def _normalize_clarification_answer(ans):
    """
    Blank -> None (drop, agent uses defaults).
    A vague answer ('idk', 'standard', 'use defaults', 'not sure', ...) ->
        'use sensible standard defaults'.
    Anything concrete -> unchanged.
    """
    a = (ans or "").strip()
    if not a:
        return None
    if _VAGUE_ANSWER_RE.match(a):
        return "use sensible standard defaults"
    return a
