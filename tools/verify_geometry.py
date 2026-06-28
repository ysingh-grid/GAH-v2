"""Public geometry verifier."""

from __future__ import annotations

from tools.vlm_judge import judge_geometry_render


def verify_geometry(
    prompt: str,
    code: str,
    metrics: dict,
    render_png: str,
    prior_feedback: list | None = None,
) -> dict:
    """Verify the rendered geometry against the user's instruction.

    The VLM judge receives only the user instruction and render PNG. Other
    arguments stay in this signature for compatibility with the geometry loop.
    """
    _ = code, metrics, prior_feedback
    return judge_geometry_render(prompt=prompt, render_png=render_png)
