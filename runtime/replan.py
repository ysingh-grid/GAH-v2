"""Unified, stage-tagged re-entry into the planner (the single loop-back path).

All four failure sources — cadquery_compile, cadquery_execute / mesh_repair
(inner repair loop), forge_compile, and visual_mismatch (outer refine loop) —
come back through `replan_with_feedback`. The failure stage selects which
guidance skill the planner should read and which attempt cap applies; the
planner then returns a revised PrimitivePlan or escalates to the user.

Bounds (Q8): inner stages max 3 attempts, outer (visual) max 5. The loop checks
`is_exhausted` and, when a budget is spent, escalates rather than looping
forever.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol

from runtime.schema import PrimitivePlan, plan_to_dict

if TYPE_CHECKING:
    from runtime.planner import PlannerOutput

# Which guidance skill the planner should consult for each failure stage.
STAGE_TO_SKILL: dict[str, str] = {
    "primitive_gap": "primitive_planning",
    "cadquery_compile": "repair_guidance",
    "cadquery_execute": "repair_guidance",
    "mesh_repair": "repair_guidance",
    "forge_compile": "repair_guidance",
    "visual_mismatch": "refinement_guidance",
}

# Inner (repair) stages share one cap; the outer (visual) loop has its own.
_INNER_STAGES = {
    "primitive_gap",
    "cadquery_compile",
    "cadquery_execute",
    "mesh_repair",
    "forge_compile",
}
INNER_CAP = 3
OUTER_CAP = 5


class PlannerFn(Protocol):
    """A planner turn: (original_prompt, chat_history) -> PlannerOutput."""

    def __call__(
        self, original_prompt: str, chat_history: list[dict[str, str]]
    ) -> PlannerOutput: ...


def cap_for_stage(stage: str) -> int:
    """Return the attempt cap for a failure stage (inner=3, outer=5)."""
    return INNER_CAP if stage in _INNER_STAGES else OUTER_CAP


def is_exhausted(stage: str, attempt: int) -> bool:
    """True when `attempt` has reached this stage's cap."""
    return attempt >= cap_for_stage(stage)


def build_feedback_message(failure_stage: str, detail: str, last_plan: PrimitivePlan) -> str:
    """Compose the corrective instruction handed back to the planner."""
    skill = STAGE_TO_SKILL.get(failure_stage, "repair_guidance")
    plan_json = json.dumps(plan_to_dict(last_plan), indent=2)
    return (
        f"Your previous PrimitivePlan failed at stage '{failure_stage}'.\n"
        f"Failure detail:\n{detail}\n\n"
        f"Read the '{skill}' skill, then return a corrected plan_ready that fixes "
        f"this, or ask_user if you genuinely need more information from the user.\n\n"
        f"Previous plan was:\n{plan_json}"
    )


def replan_with_feedback(
    *,
    original_prompt: str,
    last_plan: PrimitivePlan,
    failure_stage: str,
    detail: str,
    prior_history: list[dict[str, str]],
    planner_fn: PlannerFn,
) -> PlannerOutput:
    """Re-enter the planner with stage-tagged failure feedback.

    Args:
        original_prompt: The user's original request.
        last_plan: The plan that just failed.
        failure_stage: One of STAGE_TO_SKILL's keys.
        detail: The concrete error / verifier feedback to show the planner.
        prior_history: Conversation history so far (appended to, not mutated).
        planner_fn: The planner turn function (injected for testability).

    Returns:
        The planner's next PlannerOutput — a revised plan or an ask_user.
    """
    history = [
        *prior_history,
        {"role": "system", "content": build_feedback_message(failure_stage, detail, last_plan)},
    ]
    return planner_fn(original_prompt, history)


def collect_feedback_detail(stage: str, payload: dict[str, Any]) -> str:
    """Extract a human-readable failure detail from a stage's result payload."""
    if stage == "visual_mismatch":
        return str(payload.get("feedback", "verifier rejected the geometry"))
    return str(payload.get("error") or payload.get("feedback") or "unknown failure")
