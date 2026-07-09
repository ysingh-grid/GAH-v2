"""Unified, stage-tagged re-entry into the replanner (the single loop-back path).

EVERY failure source — primitive_gap, cadquery_compile, cadquery_execute,
mesh_repair, verifier_error (all inner repair loop), and visual_mismatch (outer
refine loop) — comes back through `replan_with_feedback`. No stage is ever
fail-fast; the replanner always gets a chance, bounded by its cap. The failure
stage picks the attempt cap; the replanner itself picks which guide to read
from REPLAN_SKILLS (always passed in full, not pre-selected by stage) and
always returns a revised PrimitivePlan — there is no escalate-to-user escape
hatch; it must resolve ambiguity itself.

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

# Replan guide index — name + one-line purpose, always passed in full so the
# replanner picks the guide matching its own failure, instead of the host
# pre-selecting by stage. Keep in sync with skills/*.md if a guide's role changes.
REPLAN_SKILLS: tuple[tuple[str, str], ...] = (
    ("repair_guidance", "fix a compiler/execution/mesh error in an existing plan"),
    ("refinement_guidance", "adjust parameters/positioning from visual verifier feedback"),
    ("primitive_planning", "swap or reselect a primitive when the wrong one was chosen"),
    ("dimension_reasoning", "recompute offsets, clearances, or stacked/relative dimensions"),
)

# Inner (repair) stages share one cap; the outer (visual) loop has its own.
# verifier_error (VLM transport/parse failure, e.g. truncated JSON) is inner —
# it's not a plan defect, but it still gets a bounded replan pass rather than
# an immediate fail, same as every other stage.
_INNER_STAGES = {
    "primitive_gap",
    "cadquery_compile",
    "cadquery_execute",
    "mesh_repair",
    "hollow_missing",
    "verifier_error",
}
INNER_CAP = 5
# 2 gave only 1 replan chance for visual_mismatch — one miss and the design failed
# outright even when the fix was plausibly reachable. 3 gives 2 replan attempts.
OUTER_CAP = 3


class PlannerFn(Protocol):
    """A planner turn: (original_prompt, chat_history, current_plan?) -> PrimitivePlan.

    current_plan is the plan being revised, as a plain dict — threaded so the
    replanner receives it structurally in context['current_plan'] instead of
    having to parse it out of chat text. None for a fresh (non-replan) plan.

    Raises on unrecoverable failure — there is no ask_user return value; callers
    (runtime.loop / temporal.activities.replan_activity) catch and categorize."""

    def __call__(
        self,
        original_prompt: str,
        chat_history: list[dict[str, str]],
        current_plan: dict[str, Any] | None = None,
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


def format_feature_findings(findings: list[dict[str, Any]]) -> str:
    """Render per-feature verifier findings as an actionable block.

    findings come from the grounded judge (Task 3): each is
    {feature, status: present|missing|wrong, note: specific fix}. This turns
    the replanner's input from a single vague sentence into a per-feature to-do
    list with concrete dimensional/positional fixes. Returns "" when empty.
    """
    rows: list[str] = []
    for f in findings or []:
        if not isinstance(f, dict):
            continue
        feature = str(f.get("feature", "")).strip() or "(unnamed feature)"
        status = str(f.get("status", "")).strip().upper() or "?"
        note = str(f.get("note", "")).strip()
        rows.append(f"- {feature}: {status}" + (f" — {note}" if note else ""))
    if not rows:
        return ""
    return "Per-feature verifier findings (fix the MISSING/WRONG ones):\n" + "\n".join(rows)


def _plan_step_inventory(last_plan: PrimitivePlan) -> str:
    """A compact id → operation → primitive map so findings map to steps to edit."""
    rows: list[str] = []
    for step in plan_to_dict(last_plan).get("steps", []):
        if "operation" in step:  # PrimitiveStep
            rows.append(f"- {step.get('id')}: {step.get('operation')} {step.get('primitive')}")
        else:  # FinishStep
            rows.append(f"- {step.get('id')}: finish {step.get('op')}")
    if not rows:
        return ""
    return "Current plan steps (id: operation primitive) — edit these:\n" + "\n".join(rows)


def is_shell_fail(detail: str) -> bool:
    """True when failure text is a typed or raw OCCT shell kernel failure."""
    d = (detail or "").lower()
    if "shell_fail" in d or "cannot shell" in d:
        return True
    if "finish shell" in d:
        return True
    kernel = "brep_api" in d or "command not done" in d or "stdfail" in d
    if kernel and ("shell" in d):
        return True
    return False


SHELL_FAIL_REWRITE = (
    "CAUSE: shell_fail — shell finish is NON-VIABLE on this solid (OCCT kernel). "
    "MANDATORY (not optional): DELETE every finish step with op=shell. Then either "
    "(1) FINAL the solid body only, or (2) hollow with cut steps (inner offset "
    "solids; compiler fuses all cuts into one cavity). Do NOT retweak union "
    "overlaps or shell thickness. Do NOT call preview_plan until shell is gone."
)


def build_feedback_message(failure_stage: str, detail: str, last_plan: PrimitivePlan) -> str:
    """Compose a LEAN corrective instruction for the replanner.

    Deliberately does NOT embed full skill markdown every time (that was ~8k+
    chars × every replan and dominated latency). Cause-specific detail + step
    inventory + short operator rules are enough; current_plan is structural.
    """
    skill_name = STAGE_TO_SKILL.get(failure_stage, "playbook_replan")
    note = _VERIFIER_ERROR_NOTE if failure_stage == "verifier_error" else ""
    step_inventory = _plan_step_inventory(last_plan)
    inventory_block = (
        f"=== CURRENT PLAN STEPS ===\n{step_inventory}\n\n" if step_inventory else ""
    )
    # Compact operator cheat-sheet (general geometry, not product recipes).
    rules = (
        "OPERATOR RULES (general):\n"
        "- shell_fail: DELETE shell finish; solid-only OR cavity cuts — never nudge dims.\n"
        "- cut_sever: shrink/reconnect cavity tools so walls stay one solid; "
        "all cuts are fused by the compiler — fix SIZE not cut order.\n"
        "- union_gap: overlap unions into the parent (~0.5–1mm).\n"
        "- multi-shell: open enclosed voids to the outside.\n"
        "- shell-then-union: illegal; hollow last or use cavity cuts on solid body.\n"
        "- Prefer FINAL in one REPL block; deep-copy context['current_plan'].\n"
        f"- Optional: read_skill({skill_name!r}) only if the detail is unclear.\n"
    )
    shell_block = ""
    if is_shell_fail(detail) or plan_has_shell_finish(last_plan):
        # If the plan still carries a shell and we failed execute, force rewrite.
        if is_shell_fail(detail):
            shell_block = f"=== MANDATORY REWRITE ===\n{SHELL_FAIL_REWRITE}\n\n"
    return (
        f"Your previous PrimitivePlan failed at stage '{failure_stage}'.\n"
        f"Failure detail:\n{detail}\n"
        f"{note}\n"
        f"{shell_block}"
        f"{inventory_block}"
        f"{rules}\n"
        f"Apply the fix required by the CAUSE class, then FINAL the plan. "
        f"context['current_plan'] is ready — edit that; do not spawn sub-agents."
    )


def plan_has_shell_finish(plan: PrimitivePlan | dict | None) -> bool:
    """True if the plan still contains a shell FinishStep."""
    if plan is None:
        return False
    if isinstance(plan, dict):
        steps = plan.get("steps") or []
        return any(isinstance(s, dict) and s.get("op") == "shell" for s in steps)
    for step in plan.steps:
        from runtime.schema import FinishOp, FinishStep

        if isinstance(step, FinishStep) and step.op is FinishOp.shell:
            return True
    return False


def enrich_execute_failure_detail(detail: str, plan: PrimitivePlan | None = None) -> str:
    """Ensure shell/kernel failures carry typed CAUSE + rewrite (general)."""
    text = str(detail or "")
    if is_shell_fail(text) and "CAUSE: shell_fail" not in text:
        text = f"{SHELL_FAIL_REWRITE}\n\nOriginal error:\n{text}"
    elif plan is not None and plan_has_shell_finish(plan) and is_shell_fail(text):
        if "MANDATORY REWRITE" not in text:
            text = f"{SHELL_FAIL_REWRITE}\n\n{text}"
    return text


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
    return _retry_planner_call(
        original_prompt, history, planner_fn, max_attempts, plan_to_dict(last_plan)
    )


def _retry_planner_call(
    original_prompt: str,
    history: list[dict[str, str]],
    planner_fn: PlannerFn,
    max_attempts: int,
    current_plan: dict[str, Any] | None = None,
) -> PrimitivePlan:
    """Shared retry-the-call loop for replan_with_feedback and replan_for_edit."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return planner_fn(original_prompt, history, current_plan=current_plan)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "replan call attempt %d/%d failed: %s", attempt, max_attempts, exc,
            )
    assert last_exc is not None  # noqa: S101 — loop always runs >=1 time (max_attempts >= 1)
    raise last_exc


def build_edit_message(edit_text: str, last_plan: PrimitivePlan) -> str:
    """Compose the edit instruction handed to the replanner.

    Edit-framed, not failure-framed — parallel to build_feedback_message but
    for a user-requested change to an already-generated, already-valid model,
    not a downstream error. The plan is delivered structurally via
    context['current_plan'] (see run_replanner_turn), so it is NOT embedded here.
    """
    _ = last_plan  # delivered as context['current_plan']; not embedded as parse-prone text
    return (
        f"The user wants to EDIT the current model. This is a fresh request, "
        f"not a failure — the current plan (a ready dict at context['current_plan']) "
        f"is already valid and was generated successfully.\n\n"
        f"Requested change:\n{edit_text}\n\n"
        f"Apply ONLY this change. Keep every other step byte-for-byte identical "
        f"unless the change requires touching it. Resolve any remaining "
        f"ambiguity yourself with reasonable defaults — there is no option to "
        f"ask the user.\n\n"
        f"Deep-copy context['current_plan'], apply the change, and FINAL it. Do NOT "
        f"reconstruct the plan from this text, and do NOT call llm_query / spawn sub-agents."
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
    return _retry_planner_call(
        original_prompt, history, planner_fn, max_attempts, plan_to_dict(last_plan)
    )


def _has_shell_then_union(plan: dict[str, Any] | None) -> bool:
    """Delegate to runtime.plan_guards (single source of truth)."""
    from runtime.plan_guards import has_shell_then_union_dict

    return has_shell_then_union_dict(plan)


def disconnected_cause_hint(
    plan: dict[str, Any] | None,
    *,
    num_solids: int | None = None,
    num_shells: int | None = None,
) -> str:
    """Root-cause-targeted guidance for a disconnected (num_components>1) result.

    Taxonomy (checked in order) — NOT a single 'touching unions' story:
      1. num_solids > 1           → severing cuts / multi-body compound
      2. plan shell-then-union    → vessel anti-pattern
      3. num_solids==1, shells>1  → enclosed void / multi-shell BREP
      4. else                     → true non-overlap unions (extend 0.5–1mm)
    """
    if num_solids is not None and num_solids > 1:
        from runtime.plan_guards import has_cap_style_secondary_body
        from runtime.schema import plan_from_dict

        try:
            typed = plan_from_dict(plan) if isinstance(plan, dict) else None
        except Exception:
            typed = None
        if typed is not None and has_cap_style_secondary_body(typed):
            return (
                f" CAUSE: union_gap / secondary body ({num_solids} solids) — a "
                "named cap/lid/plug union is out of single-part scope. Remove "
                "secondary bodies; keep ONE connected solid."
            )
        # Prefer cut_sever when the plan has cut steps (most multi-solids after
        # two-phase compile are still from oversize cavity tools).
        has_cut = False
        if isinstance(plan, dict):
            has_cut = any(
                isinstance(s, dict) and s.get("operation") == "cut"
                for s in (plan.get("steps") or [])
            )
        if has_cut:
            return (
                f" CAUSE: cut_sever ({num_solids} OCCT solids) — a cavity cut "
                "disconnected walls (often a through-cut larger than the body it "
                "passes through, freeing a rim). Shrink cavity tools so walls stay "
                "continuous; the compiler already fuses all cuts into one tool — "
                "fix cavity SIZE/alignment, not cut order. Do NOT only nudge z by 1mm."
            )
        return (
            f" CAUSE: union_gap ({num_solids} OCCT solids) — additive features did "
            "not fuse. Extend each union into its parent (~0.5–1mm overlap); "
            "patterned spokes must sink into hub and rim."
        )
    if _has_shell_then_union(plan):
        return (
            " CAUSE: shell-then-union — a solid was unioned onto a shelled wall. "
            "Either hollow LAST (all additive first, then shell once) or express "
            "the hollow as fused cavity cuts on a solid body."
        )
    if (
        num_solids is not None
        and num_solids == 1
        and num_shells is not None
        and num_shells > 1
    ):
        return (
            f" CAUSE: multi-shell solid (1 solid, {num_shells} shells) — enclosed "
            "internal void (balloon). Open the cavity to the outside (through-path "
            "or open face); never leave a sealed internal cavity."
        )
    return (
        " CAUSE: disconnected components — features only TOUCH instead of "
        "overlapping. Extend each union feature ~0.5-1mm INTO the body it joins "
        "so the boolean fuses one watertight solid."
    )


def collect_feedback_detail(
    stage: str, payload: dict[str, Any], plan: dict[str, Any] | None = None
) -> str:
    """Extract a human-readable failure detail from a stage's result payload.

    `plan` (optional) plus optional `num_solids` / `num_shells` on the payload
    drive the disconnected-taxonomy hint (see disconnected_cause_hint).
    """
    if stage == "visual_mismatch":
        base = str(payload.get("feedback", "verifier rejected the geometry"))
        findings = format_feature_findings(payload.get("feature_findings") or [])
        return f"{base}\n\n{findings}" if findings else base
    if stage == "mesh_repair":
        # repair_mesh returns {success, after, actions, ...} with NO error/feedback
        # key when it ran but the mesh still didn't pass. Surface the actual mesh
        # stats so the replanner can act instead of seeing "unknown failure".
        after = payload.get("after") or {}
        if after:
            actions = ", ".join(payload.get("actions") or []) or "none"
            base = (
                f"mesh still invalid after repair: "
                f"watertight={after.get('is_watertight')}, "
                f"open_holes={after.get('open_holes')}, "
                f"self_intersections={after.get('self_intersections')}, "
                f"components={after.get('num_components')}. Repairs tried: {actions}."
            )
            if (after.get("num_components") or 1) > 1:
                # Topology from execute (preferred) may be stashed on the payload
                # by the geometry loop so we pick the right CAUSE class.
                n_sol = payload.get("num_solids")
                n_sh = payload.get("num_shells")
                if n_sol is None:
                    n_sol = after.get("num_solids")
                if n_sh is None:
                    n_sh = after.get("num_shells")
                base += disconnected_cause_hint(
                    plan,
                    num_solids=int(n_sol) if n_sol is not None else None,
                    num_shells=int(n_sh) if n_sh is not None else None,
                )
            return base
        return str(payload.get("error") or payload.get("feedback") or "mesh repair failed")
    return str(payload.get("error") or payload.get("feedback") or "unknown failure")
