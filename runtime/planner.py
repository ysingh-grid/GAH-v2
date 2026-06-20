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
    list_skills,
    lookup_primitive,
    read_skill,
    web_search,
)
from runtime.schema import PrimitivePlan

if TYPE_CHECKING:
    from fast_rlm import RLMConfig

_PLANNER_TOOLS = [list_primitives, lookup_primitive, list_skills, read_skill, web_search]

PLANNER_TASK = """\
You are the PLANNER in a text-to-CAD system. You talk to the user through a chat
bubble to pin down a single mechanical part, then emit a typed PrimitivePlan.

Read the `playbook` skill FIRST (use read_skill), then the skills it points to.

Your job each turn:
1. Read `original_prompt` and the `chat_history` you are given.
2. If a needed measurement is missing or ambiguous, look it up with web_search
   (standard sizes, typical dimensions) and ALWAYS present the user concrete
   options. Then return action="ask_user" with one focused question and
   suggested_options.
3. Only when you have every dimension and constraint needed to build the part,
   return action="plan_ready" with a PrimitivePlan built from library primitives
   (use list_primitives / lookup_primitive). Do NOT write CadQuery code.
4. If the part needs geometry no library primitive can express, ask the user to
   simplify, or explain the limitation via action="ask_user".

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
