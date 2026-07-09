"""Per-turn RLM planner: one user message in, one validated PrimitivePlan out.

The backend re-invokes `run_planner_turn` on every user message with the full
chat history. The RLM must always resolve the request to a validated
PrimitivePlan — there is no clarifying-question escape hatch; ambiguity gets
resolved with reasonable defaults, not punted back to the user. output_schema
is the PrimitivePlan itself, so the model's FINAL is schema-checked (and
self-corrected on mismatch) by fast-rlm before we ever see it.

This module owns the *pure* pieces (the output contract, the task prompt, the
result parser). The single impure call — `fast_rlm.run` — is isolated in
`run_planner_turn` so everything else is unit-testable without network or cost.

Callers must handle exceptions: run_planner_turn/run_replanner_turn raise on
unrecoverable failure (budget exhausted, no FINAL emitted, a schema mismatch
fast-rlm's own retry loop couldn't resolve) instead of masking it as a fake
user-facing question.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)


def _llm_kwargs() -> dict:
    """Generation params (temperature/seed/top_p) for every fast_rlm.run call.

    Lazy import keeps this module import-safe without rlm_config (mirrors how
    `config` is lazily imported below). fast_rlm.run spreads these into every
    chat.completions.create call (root + all delegate_features sub-agents), so
    setting them once per run() covers the whole agent tree."""
    from rlm.rlm_config import LLM_KWARGS

    return LLM_KWARGS


# Tools the planner may call inside its REPL. Imported as objects so fast-rlm
# can extract their source; they must stay self-contained (see rlm/pull_tools).
from rlm.pull_tools import (
    delegate_features,
    list_skills,
    lookup_design_reference,
    lookup_primitive,
    preview_plan,
    read_skill,
)
from runtime.schema import PrimitivePlan

if TYPE_CHECKING:
    from fast_rlm import RLMConfig

_PLANNER_TOOLS = [
    read_skill,
    list_skills,
    lookup_primitive,
    lookup_design_reference,
    preview_plan,
    delegate_features,
]
# delegate_stage is intentionally NOT exposed. Measured: per-stage child delegation
# spawns a full agent per stage over tiny context = pure overhead; it drove a single
# solid to >1M tokens / runaway. The def is kept in rlm/pull_tools.py but isolated.
# delegate_features stays (genuine compound multi-solid assemblies). NOTE: isolating
# delegate_features too gave NO token benefit (pure-inline box still ~183k/17 steps),
# so the bloat is the monolithic root's per-step context growth + flash's step count,
# not delegation alone.

_REPLANNER_TOOLS = [
    read_skill,
    list_skills,
    lookup_primitive,
    lookup_design_reference,
    preview_plan,
]
# delegate_features intentionally absent: a replan edits ONE existing plan, it
# never decomposes a new assembly, so the fork tool has no legitimate use here.
# If you add a new tool to _PLANNER_TOOLS, it does NOT automatically appear here
# — add it explicitly only if the replanner genuinely needs it.


def parse_planner_result(result: Any) -> PrimitivePlan:
    """Validate a fast-rlm FINAL dict into a PrimitivePlan (raises on mismatch)."""
    if isinstance(result, PrimitivePlan):
        return result
    return PrimitivePlan.model_validate(result)


def _load_core_skills() -> dict[str, str]:
    """Load core skills from the skills directory directly to avoid REPL roundtrips."""
    import os
    skills_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")
    loaded = {}
    for name in ["playbook", "primitive_planning"]:
        path = os.path.join(skills_dir, f"{name}.md")
        try:
            with open(path, encoding="utf-8") as f:
                loaded[name] = f.read()
        except Exception as e:
            logger.warning(f"Failed to pre-load skill {name}: {e}")
    return loaded


def _load_available_primitives() -> dict[str, str]:
    """Load primitives with 1-line descriptions from library.json for the Rich Menu."""
    from runtime.schema import load_library
    try:
        lib = load_library()
        return {name: spec.get("description", "") for name, spec in lib.items()}
    except Exception as e:
        logger.warning(f"Failed to build Rich Menu: {e}")
        return {}


PLANNER_TASK = """\
You are the PLANNER. Turn the user's request (original_prompt, plus any
chat_history) into ONE validated PrimitivePlan.

Your playbook and core skills are already loaded in `context['preloaded_skills']`.
Read them directly from context. Do NOT call `read_skill()` for 'playbook' or
'primitive_planning'—they are already available. Resolve ambiguity with
reasonable defaults; there is no option to ask the user.

For a TRIVIAL single-primitive part, emit FINAL in one block. For a COMPLEX part
(a real assembly, or many features/patterns/stacked parts), you MUST call
`preview_plan(plan_dict)` to check the REAL geometry BEFORE FINAL — fix any
disconnected (num_components > 1) or mis-sized feature it reveals — bounded to at
most 2 preview calls. See the GROUNDED SELF-CHECK section of the playbook.
"""


def build_planner_query(
    original_prompt: str,
    chat_history: list[dict[str, str]],
    *,
    available_primitives: dict[str, str] | None = None,
    preloaded_skills: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Assemble the structured context dict handed to the RLM for one turn.

    MENU by value, CONTENT by reference. available_primitives (a Rich Menu of keys and 
    1-line descriptions) is preloaded on the host — cheaper than making the monolithic 
    root spend extra REPL steps to pull it. The large primitive schemas are pulled 
    by reference only when needed via lookup_primitive().
    """
    # task = the planner's standing instruction; the user's actual request lives
    # ONLY in original_prompt/chat_history. (task used to duplicate original_prompt
    # byte-for-byte — pure wasted context on every REPL step.)
    query: dict[str, Any] = {
        "task": PLANNER_TASK,
        "original_prompt": original_prompt,
        "chat_history": chat_history,
    }
    if available_primitives is not None:
        query["available_primitives"] = available_primitives
    if preloaded_skills is not None:
        query["preloaded_skills"] = preloaded_skills
    return query


def run_planner_turn(
    original_prompt: str,
    chat_history: list[dict[str, str]],
    *,
    backend_url: str,
    config: RLMConfig | None = None,
) -> PrimitivePlan:
    """Run one planner turn against the RLM and return its validated plan.

    Args:
        original_prompt: The user's first request.
        chat_history: Prior turns as [{"role": "user"|"planner", "content": str}].
        backend_url: Base URL of the product backend, injected into the REPL as
            DTCM_BACKEND_URL so the pull tools can reach it.
        config: Optional fast-rlm RLMConfig; defaults to rlm.rlm_config.config.

    Returns:
        A validated PrimitivePlan.

    Raises:
        Whatever fast-rlm/parse_planner_result raise on unrecoverable failure
        (budget exhaustion, no FINAL emitted, a schema mismatch the engine's own
        retry loop couldn't resolve). Callers must handle this — there is no
        graceful ask_user fallback here.
    """
    import os

    import fast_rlm

    if config is None:
        from rlm.rlm_config import config as default_config

        config = default_config

    # Pre-fetch the Rich Menu (catalog keys + 1-line descriptions) and embed them
    # so the monolithic root skips list_primitives() — cheaper than REPL round-trips.
    # The large schemas are still pulled by reference inside the REPL via lookup_primitive().
    os.environ["DTCM_BACKEND_URL"] = backend_url
    available_primitives = _load_available_primitives()

    preloaded_skills = _load_core_skills()

    result = fast_rlm.run(
        build_planner_query(
            original_prompt,
            chat_history,
            available_primitives=available_primitives,
            preloaded_skills=preloaded_skills,
        ),
        config=config,
        tools=_PLANNER_TOOLS,
        output_schema=PrimitivePlan,
        env_variables={
            "DTCM_BACKEND_URL": backend_url,
        },
        llm_kwargs=_llm_kwargs(),
    )
    return parse_planner_result(result["results"])


REPLANNER_TASK = """\
You are the REPLANNER. A plan already exists and needs ONE revision — the failure
(or edit request) is in the last message of chat_history.

The current plan is provided as a READY dict at `context['current_plan']`. Work
from THAT directly:
    import copy
    plan = copy.deepcopy(context['current_plan'])
    # ...apply ONLY the minimal fix the feedback names (e.g. rename a bad param,
    #    resize/move one step)...
    FINAL(plan)
Do NOT try to parse the plan out of chat_history text, and do NOT call
`llm_query` or spawn sub-agents — everything you need is already in context.
Change only what the request calls for; keep every other step unchanged.

Your playbook and core skills are in `context['preloaded_skills']` — read them
from context; do NOT call `read_skill()` for 'playbook'/'primitive_planning'.

If your fix materially changes the geometry of a COMPLEX part (moves/resizes a
feature, adds/removes a body), you MAY verify it with `preview_plan(plan)` before
FINAL — at most 2 preview calls. A one-parameter tweak needs no preview. Aim to
FINAL in a single REPL block.
"""


def run_replanner_turn(
    original_prompt: str,
    chat_history: list[dict[str, str]],
    *,
    backend_url: str | None = None,
    config: RLMConfig | None = None,
    current_plan: dict[str, Any] | None = None,
) -> PrimitivePlan:
    """Run one replan turn against the scoped replanner toolset (no fork tool).

    Args:
        original_prompt: The user's original request.
        chat_history: Prior turns plus the trailing feedback/edit system message
            (see runtime.replan.replan_with_feedback).
        backend_url: Base URL of the product backend, injected into the REPL as
            DTCM_BACKEND_URL so the read-only pull tools can reach it.
        config: Optional fast-rlm RLMConfig; defaults to rlm.rlm_config.config.
        current_plan: The plan being revised, as a plain dict. Injected into the
            query as context['current_plan'] so the replanner edits it directly
            instead of re-parsing it out of chat text (which caused a REPL
            "unterminated string literal" flail + wasteful sub-agent spawns).

    Returns:
        A validated, corrected PrimitivePlan.

    Raises:
        Same as run_planner_turn — no graceful ask_user fallback. Callers
        (replan_activity / the in-process loop) handle the failure explicitly.
    """
    import os

    import fast_rlm

    if config is None:
        from rlm.rlm_config import config as default_config
        config = default_config

    if backend_url:
        os.environ["DTCM_BACKEND_URL"] = backend_url

    # Pre-fetch the Rich Menu (catalog keys + 1-line descriptions) and embed them
    # so the monolithic root skips list_primitives() — cheaper than REPL round-trips.
    # The large schemas are still pulled by reference inside the REPL via lookup_primitive().
    available_primitives = _load_available_primitives()
    preloaded_skills = _load_core_skills()

    query: dict[str, Any] = {
        "task": REPLANNER_TASK,
        "original_prompt": original_prompt,
        "chat_history": chat_history,
        "preloaded_skills": preloaded_skills,
    }
    if available_primitives:
        query["available_primitives"] = available_primitives
    if current_plan is not None:
        # Deliver the plan STRUCTURALLY so the replanner edits context['current_plan']
        # directly — never re-parsing it from chat text (the parse flail).
        query["current_plan"] = current_plan
    result = fast_rlm.run(
        query,
        config=config,
        tools=_REPLANNER_TOOLS,
        output_schema=PrimitivePlan,
        env_variables={
            "DTCM_BACKEND_URL": backend_url or "",
        },
        llm_kwargs=_llm_kwargs(),
    )
    return parse_planner_result(result["results"])
