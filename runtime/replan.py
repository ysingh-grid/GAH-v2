"""Unified, stage-tagged re-entry into the replanner (the single loop-back path).

EVERY failure source — primitive_gap, cadquery_compile, cadquery_execute,
mesh_repair, verifier_error (all inner repair loop), and visual_mismatch (outer
refine loop) — comes back through `replan_with_feedback`. No stage is ever
fail-fast; the replanner always gets a chance, bounded by its cap. The failure
stage picks the attempt cap AND the one guide the feedback message steers to
(STAGE_TO_SKILL); the replanner discovers its FULL guide catalog via its
list_skills_replan tool (single source: skills/SKILLS_replan.md) and always
returns a revised PrimitivePlan — there is no escalate-to-user escape hatch; it
must resolve ambiguity itself.

Bounds (Q8): inner (repair) stages max 5 attempts, outer (visual) max 3 — this
caps how many times the geometry loop re-enters replan after a NEW downstream
failure. Separately, each individual replan CALL retries up to
REPLAN_CALL_RETRIES (2) times if it raises (flaky LLM call), before that one
attempt counts as a failure against the stage cap above.

History contract (state across plan->replan rounds): the base is the
pre-planner intake facts ONLY — never the raw chatbot conversation. On top of
that, the caller (runtime.loop / temporal.workflow) appends each prior round's
(failed plan + failure) pair, and replan_with_feedback appends the CURRENT
round's feedback message (which embeds the current plan + detail + guide
index). So every replan sees the full plan lineage, bounded by the caps.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from runtime.schema import PrimitivePlan, plan_to_dict

logger = logging.getLogger(__name__)

# How many times a single replan CALL retries on its own failure (LLM exception,
# budget exhaustion, malformed FINAL) before giving up. Distinct from INNER_CAP/
# OUTER_CAP below — those bound how many times the geometry loop re-enters replan
# after a NEW downstream failure; this bounds retries of one flaky replan attempt.
REPLAN_CALL_RETRIES = 2

# Recognized failure stages (kept for cap lookup / trace categorization —
# see cap_for_stage below and runtime.trace.category_for_stage).
STAGE_TO_SKILL: dict[str, str] = {
    "primitive_gap": "primitive_planning",
    "cadquery_compile": "repair_guidance",
    "cadquery_execute": "repair_guidance",
    "mesh_repair": "repair_guidance",
    "verifier_error": "repair_guidance",
    "visual_mismatch": "refinement_guidance",
}

# Inner (repair) stages share one cap; the outer (visual) loop has its own.
# verifier_error (VLM transport/parse failure, e.g. truncated JSON) is inner —
# it's not a plan defect, but it still gets a bounded replan pass rather than
# an immediate fail, same as every other stage.
_INNER_STAGES = {
    "primitive_gap",
    "cadquery_compile",
    "cadquery_execute",
    "mesh_repair",
    "verifier_error",
}
INNER_CAP = 5
# 2 gave only 1 replan chance for visual_mismatch — one miss and the design failed
# outright even when the fix was plausibly reachable. 3 gives 2 replan attempts.
OUTER_CAP = 3


class PlannerFn(Protocol):
    """A planner turn: (original_prompt, chat_history) -> PrimitivePlan.

    Raises on unrecoverable failure — there is no ask_user return value; callers
    (runtime.loop / temporal.activities.replan_activity) catch and categorize."""

    def __call__(
        self, original_prompt: str, chat_history: list[dict[str, str]]
    ) -> PrimitivePlan: ...


def cap_for_stage(stage: str) -> int:
    """Return the attempt cap for a failure stage (inner=5, outer=2)."""
    return INNER_CAP if stage in _INNER_STAGES else OUTER_CAP


def is_exhausted(stage: str, attempt: int) -> bool:
    """True when `attempt` has reached this stage's cap."""
    return attempt >= cap_for_stage(stage)


_VERIFIER_ERROR_NOTE = (
    "\nNote: this specific stage means the visual verifier itself failed to "
    "respond validly (e.g. a truncated/malformed judge response) — it is NOT a "
    "verdict on your plan, which may well be correct. If nothing in the guides "
    "or plan looks wrong, you may return the plan unchanged; only change it if "
    "you spot something that plausibly makes the render/judge call harder than "
    "it needs to be (e.g. degenerate geometry, an oversized part filling the frame).\n"
)


def build_feedback_message(failure_stage: str, detail: str, last_plan: PrimitivePlan) -> str:
    """Compose the corrective instruction handed back to the replanner."""
    # Compact separators, not indent=2: this string is read only by the LLM, and
    # pretty-printing costs ~55% more bytes on every replan attempt for nothing.
    plan_json = json.dumps(plan_to_dict(last_plan), separators=(",", ":"))
    # Steer to the ONE guide that matches this failure stage (STAGE_TO_SKILL) —
    # not a full catalog dump. The replanner discovers its complete guide list
    # via list_skills_replan() (single source: skills/SKILLS_replan.md), so no
    # second catalog lives here to drift out of sync.
    guide = STAGE_TO_SKILL.get(failure_stage, "repair_guidance")
    note = _VERIFIER_ERROR_NOTE if failure_stage == "verifier_error" else ""
    return (
        f"Your previous PrimitivePlan failed at stage '{failure_stage}'.\n"
        f"Failure detail:\n{detail}\n"
        f"{note}\n"
        f"Read the '{guide}' guide (read_skill('{guide}')) — it matches this "
        f"failure; call list_skills_replan() if you need the full guide list. "
        f"Then return a corrected plan_ready that fixes it. You must resolve "
        f"this yourself using the guides, context, and reasonable defaults — "
        f"there is no option to ask the user.\n\n"
        f"Previous plan was:\n{plan_json}"
    )


def replan_with_feedback(
    *,
    original_prompt: str,#current state only
    last_plan: PrimitivePlan,
    failure_stage: str,
    detail: str,
    prior_history: list[dict[str, str]],
    planner_fn: PlannerFn,
    max_attempts: int = REPLAN_CALL_RETRIES,
) -> PrimitivePlan:
    """Re-enter the replanner with stage-tagged failure feedback.

    Retries the CALL itself (not a new plan attempt) up to `max_attempts` times
    if planner_fn raises — covers a flaky LLM call (timeout, transient budget
    hiccup), not a new design failure. Each retry reuses the same feedback
    message; only the very last exception propagates.

    Args:
        original_prompt: The user's original request.
        last_plan: The plan that just failed.
        failure_stage: One of the recognized failure stages (see STAGE_TO_SKILL).
        detail: The concrete error / verifier feedback to show the planner.
        prior_history: Conversation history so far (appended to, not mutated).
        planner_fn: The planner turn function (injected for testability).
        max_attempts: How many times to try the replan call before giving up.

    Returns:
        The replanner's revised PrimitivePlan. Raises the last exception if
        every attempt fails — the caller decides how to categorize it.
    """
    history = [
        *prior_history,
        {"role": "system", "content": build_feedback_message(failure_stage, detail, last_plan)},
    ]
    return _retry_planner_call(original_prompt, history, planner_fn, max_attempts)


def _retry_planner_call(
    original_prompt: str,
    history: list[dict[str, str]],
    planner_fn: PlannerFn,
    max_attempts: int,
) -> PrimitivePlan:
    """Shared retry-the-call loop for replan_with_feedback and replan_for_edit."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return planner_fn(original_prompt, history)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "replan call attempt %d/%d failed: %s", attempt, max_attempts, exc,
            )
    assert last_exc is not None  # loop always runs >=1 time (max_attempts >= 1)
    raise last_exc


def build_edit_message(edit_text: str, last_plan: PrimitivePlan) -> str:
    """Compose the edit instruction handed to the replanner.

    Edit-framed, not failure-framed — parallel to build_feedback_message but
    for a user-requested change to an already-generated, already-valid model,
    not a downstream error.
    """
    plan_json = json.dumps(plan_to_dict(last_plan), separators=(",", ":"))
    return (
        f"The user wants to EDIT the current model. This is a fresh request, "
        f"not a failure — the plan below is already valid and was generated "
        f"successfully.\n\n"
        f"Requested change:\n{edit_text}\n\n"
        f"Apply ONLY this change. Keep every other step byte-for-byte identical "
        f"unless the change requires touching it. Resolve any remaining "
        f"ambiguity yourself with reasonable defaults — there is no option to "
        f"ask the user.\n\n"
        f"Current plan:\n{plan_json}"
    )


def replan_for_edit(
    *,
    original_prompt: str,
    last_plan: PrimitivePlan,
    edit_text: str,
    prior_history: list[dict[str, str]],
    planner_fn: PlannerFn,
    max_attempts: int = REPLAN_CALL_RETRIES,
) -> PrimitivePlan:
    """Re-enter the replanner with a user EDIT request — not a failure.

    Same retry-the-call mechanics as replan_with_feedback (protects against a
    flaky LLM call), but framed via build_edit_message. Deliberately does NOT
    touch INNER_CAP/OUTER_CAP: those bound how many times the loop re-enters
    replan after a NEW downstream failure, and an edit is fresh user intent,
    not a retry. The geometry loop run after this edit still enforces its own
    caps for any new compile/mesh/verify failures the edit introduces.

    Returns:
        The replanner's edited PrimitivePlan. Raises the last exception if
        every attempt fails.
    """
    history = [
        *prior_history,
        {"role": "system", "content": build_edit_message(edit_text, last_plan)},
    ]
    return _retry_planner_call(original_prompt, history, planner_fn, max_attempts)


def collect_feedback_detail(stage: str, payload: dict[str, Any]) -> str:
    """Extract a human-readable failure detail from a stage's result payload."""
    if stage == "visual_mismatch":
        return str(payload.get("feedback", "verifier rejected the geometry"))
    if stage == "mesh_repair":
        # A REJECTED repair (it degraded the mesh — volume drift / shattering)
        # carries the strongest signal: the geometry itself is broken in a way
        # meshing can't fix. Its error message already names the plan-level
        # causes to look for; lead with it.
        if payload.get("rejected"):
            return str(payload.get("error"))
        # repair_mesh returns {success, after, actions, ...} with NO error/feedback
        # key when it ran but the mesh still didn't pass. Surface the actual mesh
        # stats so the replanner can act instead of seeing "unknown failure".
        after = payload.get("after") or {}
        if after:
            actions = ", ".join(payload.get("actions") or []) or "none"
            expected = after.get("expected_components") or 1
            base = (
                f"mesh still invalid after repair: "
                f"watertight={after.get('is_watertight')}, "
                f"open_holes={after.get('open_holes')}, "
                f"self_intersections={after.get('self_intersections')}, "
                f"components={after.get('num_components')} "
                f"(expected {expected}). Repairs tried: {actions}."
            )
            # More components than the B-rep predicts means features didn't fuse —
            # almost always tangent (touching) instead of overlapping. This is the
            # single most common complex-part defect. (Matching the expected count
            # is fine: legal multi-body compounds and closed hollow parts are >1.)
            if (after.get("num_components") or 1) > expected:
                base += (
                    " CAUSE: disconnected components — unioned features only TOUCH "
                    "instead of overlapping. Extend each union feature ~0.5-1mm INTO "
                    "the body it joins (e.g. lengthen spokes so they overlap hub and "
                    "rim) so the boolean fuses one watertight solid."
                )
            return base
        return str(payload.get("error") or payload.get("feedback") or "mesh repair failed")
    return str(payload.get("error") or payload.get("feedback") or "unknown failure")
