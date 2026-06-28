"""Per-turn RLM planner: one user message in, one typed decision out.

The backend re-invokes `run_planner_turn` on every user message with the full
chat history. The RLM either asks one more clarifying question or, once it has
enough, emits a validated PrimitivePlan. That two-way decision is the
`PlannerOutput` model below, used as the fast-rlm `output_schema` so the
model's FINAL value is schema-checked before we ever see it.

This module owns the *pure* pieces (the output contract, the task prompt, the
result parser). The single impure call — `fast_rlm.run` — is isolated in
`run_planner_turn` so everything else is unit-testable without network or cost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Tools the planner may call inside its REPL. Imported as objects so fast-rlm
# can extract their source; they must stay self-contained (see rlm/pull_tools).
from rlm.pull_tools import (
    delegate_features,
    fetch_kb_sections,
    list_kb_index,
    list_primitives,
    list_skills,
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
    delegate_features,
]
# delegate_stage is intentionally NOT exposed. Measured: per-stage child delegation
# spawns a full agent per stage over tiny context = pure overhead; it drove a single
# solid to >1M tokens / runaway. The def is kept in rlm/pull_tools.py but isolated.
# delegate_features stays (genuine compound multi-solid assemblies). NOTE: isolating
# delegate_features too gave NO token benefit (pure-inline box still ~183k/17 steps),
# so the bloat is the monolithic root's per-step context growth + flash's step count,
# not delegation alone.


class PlannerOutput(BaseModel):
    """The planner's typed FINAL: either a question for the user, or a plan.

    `action` discriminates. For ask_user, `question` is required (and
    `suggested_options` is encouraged). For plan_ready, `plan` is required.
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["ask_user", "plan_ready"]
    question: str | None = None
    suggested_options: list[str] = Field(default_factory=list)
    plan: PrimitivePlan | None = None

    @model_validator(mode="after")
    def _fields_match_action(self) -> PlannerOutput:
        if self.action == "ask_user":
            if not self.question:
                raise ValueError("action 'ask_user' requires a non-empty 'question'")
        elif self.action == "plan_ready":
            if self.plan is None:
                raise ValueError("action 'plan_ready' requires a 'plan'")
        return self


def parse_planner_result(result: dict[str, Any]) -> PlannerOutput:
    """Validate a fast-rlm FINAL dict into a PlannerOutput (raises on mismatch)."""
    return PlannerOutput.model_validate(result)


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
    query: dict[str, Any] = {
        "task": original_prompt,
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
) -> PlannerOutput:
    """Run one planner turn against the RLM and return its typed decision.

    Args:
        original_prompt: The user's first request.
        chat_history: Prior turns as [{"role": "user"|"planner", "content": str}].
        backend_url: Base URL of the product backend, injected into the REPL as
            DTCM_BACKEND_URL so the pull tools can reach it.
        config: Optional fast-rlm RLMConfig; defaults to rlm.rlm_config.config.

    Returns:
        A PlannerOutput — action="ask_user" (question + options) or
        action="plan_ready" (validated PrimitivePlan).
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
        output_schema=dict,
        env_variables={
            "DTCM_BACKEND_URL": backend_url,
        },
    )
    return parse_planner_result(result["results"])

############################################# IGNORE replanner, placeholder code, doesnt work
REPLANNER_TASK = """\
You are a single-purpose FORK-AND-RETURN agent: spawned by the geometry workflow to
fix ONE failed PrimitivePlan and return the corrected plan to your parent. You are
isolated (no tools, fresh context) and you speak only to the parent that spawned you.

The failure details and the prior plan are in chat_history (the last system message).
Your job:

1. Read the failure message in chat_history[-1]["content"].
2. Identify which parameter(s) caused the failure.
3. Call FINAL immediately with the corrected plan_ready — change only what is broken.
   OR call FINAL with ask_user if fixing requires information only the user can provide.

Rules:
- Do NOT call any tools (no list_primitives, no lookup_primitive, no web_search).
- Do NOT re-derive the plan from scratch — keep all correct steps unchanged.
- Change the minimum needed to fix the reported failure.
- Do NOT inspect chat history strings or system variables; output FINAL directly.
- Emit FINAL in your very first REPL block. No intermediate steps.
"""


def run_replanner_turn(
    original_prompt: str,
    chat_history: list[dict[str, str]],
    *,
    config: RLMConfig | None = None,
) -> PlannerOutput:
    """Run one replan turn — no tools, immediate FINAL, used after geometry failure.

    Unlike run_planner_turn this gives the model NO tools. It just sees the
    failure message in chat_history and must emit a corrected plan or ask_user
    in a single REPL step.  No tool calls = no timeouts = fast replan.
    """
    import fast_rlm

    if config is None:
        from rlm.rlm_config import config as default_config
        config = default_config

    query = {
        "task": REPLANNER_TASK,
        "original_prompt": original_prompt,
        "chat_history": chat_history,
    }
    result = fast_rlm.run(
        query,
        config=config,
        tools=_PLANNER_TOOLS,
        output_schema=PlannerOutput,
    )
    return parse_planner_result(result["results"])
