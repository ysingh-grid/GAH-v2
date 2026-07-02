"""VLM intake helper for pre-RLM request summarization."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

INTAKE_INSTRUCTION = """You are a multimodal intake assistant for CAD requests.

You receive the user's request text and, when available, one or more reference
images. Your job is to summarize the request so a downstream planner can ask
good clarification questions before geometry generation begins.

Return only JSON with this shape:
{
  "mode": "image" | "text",
  "summary": "short description of the intended part or scene",
  "observations": ["visible or implied facts", "..."],
  "missing_facts": ["facts that still need clarification", "..."]
}

Rules:
- If an image is provided, describe what is visible in the image and what it
  implies about the design request.
- If no image is provided, mentally visualize the text-only request and
  summarize the intended geometry the same way.
- Keep the summary short, concrete, and geometry-oriented.
- Do not add any prose outside the JSON object.
"""


class VlmIntakeSummary(BaseModel):
    """Structured summary returned by the intake VLM."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["image", "text"]
    summary: str
    observations: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)


def summarize_design_request(
    prompt: str,
    image_parts: list[tuple[str, bytes]] | None = None,
) -> dict[str, Any]:
    """Summarize a design request with an optional image reference."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    parts = [types.Part.from_text(text=f"USER REQUEST:\n{prompt}")]
    for mime_type, data in (image_parts or [])[:3]:
        parts.append(types.Part.from_bytes(data=data, mime_type=mime_type))

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=os.environ.get("VLM_INTAKE_MODEL", "gemini-3.1-pro-preview"),
        contents=parts,
        config=types.GenerateContentConfig(
            system_instruction=INTAKE_INSTRUCTION,
            response_mime_type="application/json",
        ),
    )
    return VlmIntakeSummary.model_validate(_read_json(response.text or "")).model_dump()


def _read_json(text: str) -> dict[str, Any]:
    """Read a JSON object from a model response."""
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
