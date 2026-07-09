"""Robust google.genai text generation.

WHY: the VLM judge + intake pass `thinking_config` (ThinkingLevel), but a model can
reject it with `400 INVALID_ARGUMENT: "Thinking level is not supported for this model."`
— which crashed the verifier on EVERY call (→ verifier_error → wasteful replan loop).
This wrapper tries WITH the thinking level, and on that specific 400 retries WITHOUT it,
caching the model so subsequent calls skip thinking directly. All google.genai calls in
the codebase go through here so the whole app is robust to that model-capability drift.
"""

from __future__ import annotations

import os
from typing import Any

# Models known to reject thinking_config — skip thinking for these after the first 400.
_THINKING_UNSUPPORTED: set[str] = set()


def generate_content_text(
    *,
    model: str,
    contents: list[Any],
    system_instruction: str,
    max_output_tokens: int,
    json_response: bool = True,
    thinking: str | None = "low",
) -> str:
    """Call generate_content and return response.text.

    If the model rejects the thinking level (a 400 whose message mentions "thinking"),
    retry once WITHOUT thinking_config and remember it so later calls skip thinking.
    Raises RuntimeError when GEMINI_API_KEY is unset; re-raises any non-thinking error.
    """
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    client = genai.Client(api_key=api_key)
    # getattr-guarded so a future SDK that drops a level can't crash us at import/build.
    _levels = {
        name: getattr(types.ThinkingLevel, name.upper(), None)
        for name in ("low", "medium", "high", "minimal")
    }

    def _config(with_thinking: bool) -> types.GenerateContentConfig:
        kwargs: dict[str, Any] = {
            "system_instruction": system_instruction,
            "max_output_tokens": max_output_tokens,
        }
        if json_response:
            kwargs["response_mime_type"] = "application/json"
        level = _levels.get(thinking or "")
        if with_thinking and level is not None:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=level)
        return types.GenerateContentConfig(**kwargs)

    want_thinking = thinking is not None and model not in _THINKING_UNSUPPORTED
    try:
        resp = client.models.generate_content(
            model=model, contents=contents, config=_config(want_thinking)
        )
        return resp.text or ""
    except Exception as exc:  # noqa: BLE001 — only the thinking-400 is retried; others re-raise
        if want_thinking and "thinking" in str(exc).lower():
            _THINKING_UNSUPPORTED.add(model)  # this model can't take thinking — skip it henceforth
            resp = client.models.generate_content(
                model=model, contents=contents, config=_config(False)
            )
            return resp.text or ""
        raise
