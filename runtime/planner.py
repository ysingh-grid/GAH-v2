"""Per-turn RLM planner: one user message in, one validated PrimitivePlan out.

The backend re-invokes `run_planner_turn` on every user message with the full
chat history. The RLM must always resolve the request to a validated
PrimitivePlan — there is no clarifying-question escape hatch; ambiguity gets
resolved with reasonable defaults, not punted back to the user. output_schema
is LibraryBoundPrimitivePlan (structure + library params + construction guards),
so the model's FINAL is schema-checked (and self-corrected on mismatch) by
fast-rlm before we ever see it.

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
]
# SINGLE-OBJECT PLATFORM: the planner builds ONE connected watertight solid in a
# single monolithic FINAL. The multi-body fork tools are intentionally NOT here:
# - delegate_features (spawn child agents for "independent solids in an assembly")
#   invited disconnected multi-body plans (floating caps, N-component splits) and
#   added sub-agent latency for NO measured token benefit — isolated in
#   rlm/pull_tools.py, do not re-add. Multi-body assembly is out of scope.
# - delegate_stage: measured harmful (a full child per tiny-context stage = pure
#   overhead, drove a single solid to >1M tokens). Also isolated in pull_tools.
# A single connected object is one CSG construction tree the monolithic root
# writes directly; preview_plan lets it self-check that tree against real geometry.

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
    """Validate a fast-rlm FINAL into a library+construction-bound PrimitivePlan.

    Raises on structural mismatch, unknown params (primitive_gap), or illegal
    construction (cap body, shell-then-union). Used after fast-rlm returns; the
    same rules are in output_schema=LibraryBoundPrimitivePlan so the engine can
    schema-retry inside the same RLM call.
    """
    from runtime.schema import LibraryBoundPrimitivePlan, accept_plan, plan_to_dict

    if isinstance(result, LibraryBoundPrimitivePlan):
        return result
    if isinstance(result, PrimitivePlan):
        return accept_plan(plan_to_dict(result))
    return accept_plan(result)


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


def _load_available_primitives() -> dict[str, Any]:
    """Rich menu: description + param names/types/defaults for every primitive."""
    from runtime.schema import compact_library_menu

    try:
        return compact_library_menu()
    except Exception as e:
        logger.warning(f"Failed to build Rich Menu: {e}")
        return {}


def _load_family_context(original_prompt: str) -> dict[str, Any]:
    """Host construction family + through-path contract for the planner query."""
    from runtime.metrics_gate import extract_target_metrics
    from runtime.plan_guards import classify_construction_family

    family = classify_construction_family(original_prompt)
    targets = extract_target_metrics(original_prompt)
    ctx: dict[str, Any] = {
        "construction_family": family,
        "through_path": "required" if targets.requires_hollow else "unknown",
        "default_wall_mm": targets.wall_mm,
    }
    if targets.requires_hollow:
        ctx["through_path_rule"] = (
            "through_path is REQUIRED. Prefer outer solid only (base/union); "
            "the HOST applies wall-based auto-hollow if you omit cavity cuts. "
            "Solid silhouette without a passage is invalid for this request."
        )
    if family == "open_vessel":
        ctx["family_rules"] = (
            "open_vessel: emit ONE hollow_cylinder OR revolve as the only "
            "primitive step (optional fillet/chamfer finish only). "
            "NO separate cap/lid/plug unions. Caps are out of scope."
        )
        ctx["family_recipe"] = {
            "part_name": "open_vessel",
            "units": "mm",
            "steps": [
                {
                    "id": "vessel_body",
                    "primitive": "hollow_cylinder",
                    "operation": "base",
                    "parameters": {
                        "outer_radius": 35.0,
                        "inner_radius": 32.0,
                        "height": 180.0,
                    },
                    "position": [0.0, 0.0, 0.0],
                    "orientation": [0.0, 0.0, 0.0],
                }
            ],
        }
    return ctx


PLANNER_TASK = """\
You are the PLANNER. Turn the request into ONE PrimitivePlan. Prefer a SINGLE
REPL block that ends in FINAL (at most 2 turns). Do not print chat_history or
paginate skills unless a param name is unknown.

`context['available_primitives']` has exact param names (required). Optional:
`context['preloaded_skills']`, `construction_family` / `family_recipe` when present.

Host semantics: all cut steps are fused into ONE cavity tool then cut once — size
cavity so walls stay continuous. Unions must overlap. No shell-then-union, no
cap/lid secondary bodies. 1 solid + 1 shell after build. Resolve ambiguity with
defaults; never ask the user.
"""


def build_planner_query(
    original_prompt: str,
    chat_history: list[dict[str, str]],
    *,
    available_primitives: dict[str, Any] | None = None,
    preloaded_skills: dict[str, str] | None = None,
    family_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the structured context dict handed to the RLM for one turn.

    available_primitives includes param keys (library-bound FINAL). family_context
    injects host construction_family + vessel recipe when applicable.
    """
    query: dict[str, Any] = {
        "task": PLANNER_TASK,
        "original_prompt": original_prompt,
        "chat_history": chat_history,
    }
    if available_primitives is not None:
        query["available_primitives"] = available_primitives
    if preloaded_skills is not None:
        query["preloaded_skills"] = preloaded_skills
    if family_context:
        query.update(family_context)
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

    # Rich menu with param names + host construction family (vessel recipe when needed).
    os.environ["DTCM_BACKEND_URL"] = backend_url
    available_primitives = _load_available_primitives()
    preloaded_skills = _load_core_skills()
    family_context = _load_family_context(original_prompt)

    from runtime.schema import LibraryBoundPrimitivePlan

    result = fast_rlm.run(
        build_planner_query(
            original_prompt,
            chat_history,
            available_primitives=available_primitives,
            preloaded_skills=preloaded_skills,
            family_context=family_context,
        ),
        config=config,
        tools=_PLANNER_TOOLS,
        output_schema=LibraryBoundPrimitivePlan,
        env_variables={
            "DTCM_BACKEND_URL": backend_url,
        },
        llm_kwargs=_llm_kwargs(),
    )
    return parse_planner_result(result["results"])


REPLANNER_TASK = """\
You are the REPLANNER. ONE revision from context['current_plan'] + last failure.
Param names must match context['available_primitives']. Prefer ONE REPL → FINAL.

Read CAUSE in the failure detail:
- shell_fail: DELETE every shell finish. Solid-only OR cavity cut steps. Do NOT
  preview until shell is gone. Do NOT nudge union dims to “fix” shell.
- cut_sever: change cavity SIZE so walls stay connected (cuts already fused by
  compiler). Do not only move z by 1mm.
- union_gap: increase overlap into parent body.
- multi-shell: open enclosed voids.
- construction_error / shell-then-union / cap body: remove illegal structure.
- parameter/visual: edit only the named field.

    import copy
    plan = copy.deepcopy(context['current_plan'])
    # apply fix for the CAUSE class
    FINAL(plan)

No sub-agents. preview_plan at most once, and NEVER while a shell finish remains
after shell_fail.
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

    available_primitives = _load_available_primitives()
    preloaded_skills = _load_core_skills()
    family_context = _load_family_context(original_prompt)

    from runtime.schema import LibraryBoundPrimitivePlan

    query: dict[str, Any] = {
        "task": REPLANNER_TASK,
        "original_prompt": original_prompt,
        "chat_history": chat_history,
        "preloaded_skills": preloaded_skills,
    }
    if available_primitives:
        query["available_primitives"] = available_primitives
    query.update(family_context)
    if current_plan is not None:
        # Deliver the plan STRUCTURALLY so the replanner edits context['current_plan']
        # directly — never re-parsing it from chat text (the parse flail).
        query["current_plan"] = current_plan
    # Adaptive reasoning: a replan (fixing a geometry failure, or applying an edit)
    # is a spatial-reasoning task, unlike the common first-pass structured extraction.
    replan_kwargs = dict(_llm_kwargs())
    _replan_effort = os.environ.get("RLM_REPLAN_REASONING_EFFORT", "medium")
    if _replan_effort in (None, "", "none"):
        replan_kwargs.pop("reasoning_effort", None)
    else:
        replan_kwargs["reasoning_effort"] = _replan_effort
    result = fast_rlm.run(
        query,
        config=config,
        tools=_REPLANNER_TOOLS,
        output_schema=LibraryBoundPrimitivePlan,
        env_variables={
            "DTCM_BACKEND_URL": backend_url or "",
        },
        llm_kwargs=replan_kwargs,
    )
    return parse_planner_result(result["results"])
