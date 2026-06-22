"""Per-turn RLM planner: one user message in, one typed decision out.

The backend re-invokes `run_planner_turn` on every user message with the full
chat history. The RLM either asks one more clarifying question (gathering
measurements, optionally via web_search) or, once it has enough, emits a
validated PrimitivePlan. That two-way decision is the `PlannerOutput` model
below, used as the fast-rlm `output_schema` so the model's FINAL value is
schema-checked before we ever see it.

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
    list_primitives,
    lookup_primitive,
    web_search,
)
from runtime.schema import PrimitivePlan

if TYPE_CHECKING:
    from fast_rlm import RLMConfig

_PLANNER_TOOLS = [list_primitives, lookup_primitive, web_search]

PLANNER_TASK = """\
You are the PLANNER ORCHESTRATOR in a text-to-CAD system. You do NOT design parts
yourself. You DECOMPOSE the request into independent sub-parts and FORK one
sub-agent per sub-part. Each sub-agent designs exactly ONE sub-part and returns its
steps to YOU — sub-agents never see each other, they speak only to you. You assemble
their returns into one PrimitivePlan. This is a strict 1-to-1 fork-and-return.

## HARD BUDGET: 5 REPL steps, then you MUST emit FINAL. (A step = one block.)

## ⛔ Prohibitions:
- NEVER call web_search unless the user EXPLICITLY asked you to search in chat_history.
- NEVER fork a sub-agent for a trivial call (list_primitives) or for a user question.
  Fork ONLY to design a sub-part — that is the one fork-worthy task.

## Procedure — follow in order:

Step 1 — primitives = list_primitives()   [direct call — do NOT fork for this]

Step 2 — Decompose context["original_prompt"] into a list of independent sub-parts:
  • A simple object = ONE sub-part            ("a 20mm cube"      -> ["cube"])
  • A compound object = one sub-part per solid ("cricket bat"      -> ["blade", "handle"])
  If a REQUIRED dimension is missing and you cannot pick a sensible default, call
  FINAL with action="ask_user" NOW (do NOT fork). Offer two options:
    a) "Search the web for standard {name} dimensions"
    b) a concrete default you suggest (e.g. "M6 hex: 10mm across flats, 5mm tall").

Step 3 — FORK one sub-agent PER sub-part, IN PARALLEL, with batch_llm_query.
  Pass each child tools=[lookup_primitive] (children do NOT inherit your tools).
  Use batch_llm_query, NEVER asyncio.gather (the engine blocks gather).

    STEP_SCHEMA = {"type": "array", "items": {"type": "object"}}

    def design(part):
        return llm_query({
            "task": ("Design ONE sub-part of a CAD model. Pick the best primitive "
                     "from the catalog, call lookup_primitive(key) to get its exact "
                     "parameter names, fill them with real millimetre dimensions, and "
                     "return a JSON list of step objects: {id, primitive, operation, "
                     "parameters, position:[x,y,z], orientation:[rx,ry,rz]}."),
            "sub_part": part,
            "request": context["original_prompt"],
            "catalog": primitives,
        }, STEP_SCHEMA, tools=[lookup_primitive])

    sub_results = await batch_llm_query(*[design(p) for p in sub_parts])

Step 4 — Concatenate every child's step list into one steps array (flatten), set the
  FIRST step's operation to "base", and FINAL with:
    {"action": "plan_ready",
     "plan": {"part_name": <short_name>, "units": "mm", "steps": <all steps>}}

Return EXACTLY one of the two shapes defined by the output schema.
"""


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


def build_planner_query(original_prompt: str, chat_history: list[dict[str, str]]) -> dict[str, Any]:
    """Assemble the structured context dict handed to the RLM for one turn."""
    return {
        "task": PLANNER_TASK,
        "original_prompt": original_prompt,
        "chat_history": chat_history,
    }


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
            DTCM_BACKEND_URL so the pull tools (incl. web_search) can reach it.
        config: Optional fast-rlm RLMConfig; defaults to rlm.rlm_config.config.

    Returns:
        A PlannerOutput — action="ask_user" (question + options) or
        action="plan_ready" (validated PrimitivePlan).
    """
    import fast_rlm

    if config is None:
        from rlm.rlm_config import config as default_config

        config = default_config

    result = fast_rlm.run(
        build_planner_query(original_prompt, chat_history),
        config=config,
        tools=_PLANNER_TOOLS,
        output_schema=PlannerOutput,
        env_variables={"DTCM_BACKEND_URL": backend_url},
    )
    return parse_planner_result(result["results"])


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
        tools=[],  # no tools — fix the plan directly from the failure message
        output_schema=PlannerOutput,
    )
    return parse_planner_result(result["results"])
