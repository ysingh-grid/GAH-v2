"""Generic VLM judge for rendered geometry."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


JUDGE_INSTRUCTION = """You are a vision-language judge for generated CAD.

You receive only:
1. The user's geometry request.
2. A rendered PNG of the generated geometry.

Return only JSON:
{
  "passed": true | false,
  "failure_type": "none" | "wrong_shape" | "missing_feature" | "extra_feature" | "wrong_count" | "wrong_placement" | "wrong_proportion" | "unclear",
  "feedback": "Short explanation for the replanner. If passed, use 'All constraints met.'"
}
"""


def judge_geometry_render(prompt: str, render_png: str) -> dict[str, Any]:
    """Judge whether a render matches the user's requested geometry."""
    if not Path(render_png).exists():
        return _error(f"Render PNG not found: {render_png}", render_png)

    try:
        response_text = _call_vlm(prompt, render_png)
        return _format_verdict(_read_json(response_text), render_png)
    except Exception as exc:
        return _error(f"VLM judge failed: {exc}", render_png)


def _call_vlm(prompt: str, render_png: str) -> str:
    """Call the configured vision model with prompt + image."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    with open(render_png, "rb") as image_file:
        image_bytes = image_file.read()

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=os.environ.get("VLM_JUDGE_MODEL", "gemini-3.1-pro-preview"),
        contents=[
            types.Part.from_text(text=f"USER REQUEST:\n{prompt}"),
            types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
        ],
        config=types.GenerateContentConfig(
            system_instruction=JUDGE_INSTRUCTION,
            response_mime_type="application/json",
        ),
    )
    return response.text or ""


def _read_json(text: str) -> dict[str, Any]:
    """Read a JSON object from the VLM response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        candidate = _first_json_object(cleaned)
        return json.loads(candidate)


def _first_json_object(text: str) -> str:
    """Return the first balanced JSON object in text."""
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found")

    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start=start):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    raise ValueError("unterminated JSON object")


def _format_verdict(verdict: dict[str, Any], render_png: str) -> dict[str, Any]:
    """Return the stable payload used by the geometry loop."""
    passed = bool(verdict.get("passed"))
    failure_type = str(verdict.get("failure_type") or "wrong_shape")
    if passed:
        failure_type = "none"

    feedback = str(verdict.get("feedback") or "").strip()
    if passed:
        feedback = feedback or "All constraints met."
    elif not feedback.startswith("[visual_failure:"):
        feedback = f"[visual_failure:{failure_type}] {feedback or 'Rendered geometry does not match the request.'}"

    return {
        "passed": passed,
        "failure_type": failure_type,
        "feedback": feedback,
        "render_png": render_png,
        "verifier_ran": True,
        "failure_stage": "" if passed else "visual_mismatch",
    }


def _error(message: str, render_png: str) -> dict[str, Any]:
    """Return a fail-closed verifier error."""
    return {
        "passed": False,
        "failure_type": "verifier_error",
        "feedback": f"[verifier-error] {message}",
        "render_png": render_png,
        "verifier_ran": False,
        "failure_stage": "verifier_error",
    }
