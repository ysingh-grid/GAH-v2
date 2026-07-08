"""Public geometry verifier."""

from __future__ import annotations

from tools.vlm_judge import judge_geometry_render


def verify_geometry(
    prompt: str,
    code: str,
    metrics: dict,
    render_png: str,
    prior_feedback: list | None = None,
    feature_checklist: str = "",
) -> dict:
    """Verify the rendered geometry against the user's instruction.

    The VLM judge now receives the user instruction, the required-feature
    checklist (Task 2), the deterministic geometry metrics (bbox/volume/
    components — previously DROPPED here), the render PNG, and — on a replan
    round — the most recent replan feedback so it can check whether that fix
    landed. `code` is still accepted for loop-call compatibility but not sent.
    """
    _ = code
    last_replan_feedback = prior_feedback[-1] if prior_feedback else None
    return judge_geometry_render(
        prompt=prompt,
        render_png=render_png,
        last_replan_feedback=last_replan_feedback,
        metrics=metrics,
        feature_checklist=feature_checklist,
        feedback_history=prior_feedback,
    )
