"""Public geometry verifier."""

from __future__ import annotations

from tools.vlm_judge import judge_geometry_render


def verify_geometry(
    prompt: str,
    metrics: dict,
    render_png: str,
    prior_feedback: list | None = None,
) -> dict:
    """Verify the rendered geometry against the user's instruction.

    The VLM judge receives the user instruction, render PNG, and — on a replan
    round — the most recent replan feedback, so it can check whether that
    specific fix landed. `code`/`metrics` stay in this signature for
    compatibility with the geometry loop but aren't sent to the judge.
    """
    _ = code, metrics
    last_replan_feedback = prior_feedback[-1] if prior_feedback else None
    return judge_geometry_render(
        prompt=prompt, render_png=render_png, last_replan_feedback=last_replan_feedback
    )
