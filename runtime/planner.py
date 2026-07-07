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
    chat.completions.create call, so setting them once per run() covers the
    whole (now single-agent, no-fork) planner."""
    from rlm.rlm_config import LLM_KWARGS

    return LLM_KWARGS


# Tools the planner may call inside its REPL. Imported as objects so fast-rlm
# can extract their source; they must stay self-contained (see rlm/pull_tools).
from rlm.pull_tools import (
    fetch_kb_sections,
    list_kb_index,
    list_primitives,
    list_skills,
    list_skills_replan,
    lookup_design_reference,
    lookup_primitive,
    read_skill,
)
from runtime.schema import PrimitivePlan

if TYPE_CHECKING:
    from fast_rlm import RLMConfig

_PLANNER_TOOLS = [
    read_skill,
    list_skills,
    list_primitives,
    lookup_primitive,
    list_kb_index,
    fetch_kb_sections,
    lookup_design_reference,
]
# NO child-delegation tools. Both were removed after measurement:
#   - delegate_stage (per-stage fork) — pure overhead over tiny per-stage context;
#     drove a single solid to >1M tokens / runaway.
#   - delegate_features (per-solid fork for assemblies) — NO token benefit
#     (pure-inline box still ~183k/17 steps) AND never once invoked across logged
#     runs; the planner always planned inline / via patterns. The real cost was
#     the monolithic root's per-step context growth + flash's step count, not the
#     lack of delegation. The planner is now a flat, single-agent inline planner.

_REPLANNER_TOOLS = [
    read_skill,
    list_skills_replan,
    list_primitives,
    lookup_primitive,
    list_kb_index,
    fetch_kb_sections,
    lookup_design_reference,
]
# list_skills_replan (NOT list_skills): the replanner discovers ONLY its own
# scoped guide catalog (SKILLS_replan.md) — it never sees the planner-only
# intake/decomposition/verification guides. read_skill stays shared (access is
# open, discovery is scoped), so a guide listed in both catalogs still resolves.
# If you add a new tool to _PLANNER_TOOLS, it does NOT automatically appear here
# — add it explicitly only if the replanner genuinely needs it.


def parse_planner_result(result: Any) -> PrimitivePlan:
    """Validate a fast-rlm FINAL dict into a PrimitivePlan (raises on mismatch)."""
    if isinstance(result, PrimitivePlan):
        return result
    return PrimitivePlan.model_validate(result)


PLANNER_TASK = """\
You are the PLANNER. Turn the user's request (original_prompt, plus any
chat_history) into ONE validated PrimitivePlan.

Load your playbook guide first — it has your operating steps, skill read order,
and output contract. Resolve ambiguity with reasonable defaults; there is no
option to ask the user. Emit FINAL in as few REPL steps as possible.
"""


def build_planner_query(
    original_prompt: str,
    chat_history: list[dict[str, str]],
    *,
    available_primitives: list[str] | None = None,
    kb_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the structured context dict handed to the RLM for one turn.

    MENU by value, CONTENT by reference. available_primitives (20 catalog keys) and
    kb_index (a compact section menu) are tiny — pre-fetching them once and embedding
    them here is cheaper than making the monolithic root spend extra REPL steps to
    pull them (each added step re-sends the whole transcript — quadratic cost; this
    was MEASURED: removing the menu pushed a complex part from 326k → 464k tokens).
    The LARGE data — full primitive specs and KB section bodies — is NOT injected;
    the planner still pulls only what it needs via lookup_primitive()/
    fetch_kb_sections(). Omitted (None) → the planner falls back to the tools.
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
    if kb_index is not None:
        query["kb_index"] = kb_index
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

    # Pre-fetch the tiny MENUS once (catalog keys + KB section index) and embed them
    # so the monolithic root skips the list_primitives()/list_kb_index() REPL steps —
    # cheaper than the extra growing-context round-trips (measured). The large CONTENT
    # is still pulled by reference inside the REPL. The pull tools read
    # DTCM_BACKEND_URL from the env, so set it before the host-side pre-fetch.
    os.environ["DTCM_BACKEND_URL"] = backend_url
    try:
        available_primitives: list[str] | None = list_primitives()
    except Exception:
        available_primitives = None
    try:
        kb_index: dict[str, Any] | None = list_kb_index()
    except Exception:
        kb_index = None

    result = fast_rlm.run(
        build_planner_query(
            original_prompt,
            chat_history,
            available_primitives=available_primitives,
            kb_index=kb_index,
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
You are the REPLANNER. A plan already exists and needs ONE revision — the request
is in the last message of chat_history, along with the current plan.

Load your replan playbook guide first — it has your steps and output contract.
Change only what the request calls for; keep every other step unchanged. Emit
FINAL in as few REPL steps as possible.
"""


def run_replanner_turn(
    original_prompt: str,
    chat_history: list[dict[str, str]],
    *,
    backend_url: str | None = None,
    config: RLMConfig | None = None,
) -> PrimitivePlan:
    """Run one replan turn against the scoped replanner toolset (no fork tool).

    Args:
        original_prompt: The user's original request.
        chat_history: Prior turns plus the trailing feedback/edit system message
            (see runtime.replan.replan_with_feedback).
        backend_url: Base URL of the product backend, injected into the REPL as
            DTCM_BACKEND_URL so the read-only pull tools can reach it.
        config: Optional fast-rlm RLMConfig; defaults to rlm.rlm_config.config.

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

    # Pre-fetch ONLY the primitive-catalog menu (the same measured win as the
    # planner's pre-inject: skips a list_primitives() REPL step whose growing-
    # transcript resend costs far more than these ~20 keys). kb_index is NOT
    # injected — a replan edits an existing plan and rarely needs the KB menu;
    # the tool remains available if it does.
    available_primitives: list[str] | None = None
    if backend_url:
        try:
            available_primitives = list_primitives()
        except Exception:
            available_primitives = None

    query: dict[str, Any] = {
        "task": REPLANNER_TASK,
        "original_prompt": original_prompt,
        "chat_history": chat_history,
    }
    if available_primitives is not None:
        query["available_primitives"] = available_primitives
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
