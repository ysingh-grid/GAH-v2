"""VLM intake helper for pre-RLM request summarization."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
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
  "missing_facts": ["facts that still need clarification", "..."],
  "object_type": "the everyday name of the target object (e.g. 'foldable laptop stand')",
  "required_features": ["short feature phrases the object MUST visibly have", "..."]
}

Rules:
- If an image is provided, describe what is visible in the image and what it
  implies about the design request.
- If no image is provided, mentally visualize the text-only request and
  summarize the intended geometry the same way.
- Keep the summary short, concrete, and geometry-oriented.
- required_features is a CHECKLIST of the load-bearing, visible features that
  define this object — the things a person would notice are missing. Each entry
  MUST embed a rough proportion or spatial relation, not just a name, e.g.
  "two tall side frames (vertical walls ~40-60% of the base's long dimension)",
  "a hinge pin spanning both frames", "ventilation slots cut fully through the
  base". Prefer 3-8 entries; omit trivial finishes (a single fillet is not a
  required feature). For a plain single primitive, object_type is the shape and
  required_features may be a single entry or empty.
- Do not add any prose outside the JSON object.
"""


INTAKE_CHAT_INSTRUCTION = """You are the intake chatbot for a CAD design service.
You sit between the user and an automated geometry planner. Your ONLY job is to
gather the non-negotiable facts the planner needs, through a short back-and-forth,
then declare yourself satisfied.

Gather ONLY facts that change the geometry:
- overall size / key dimensions
- count of repeated features (holes, slots, ribs, teeth)
- critical orientation or mounting details
- material ONLY if it changes the shape

Rules:
- Ask exactly ONE short, plain-language question per turn. No jargon.
- Never re-ask something already answered in the conversation.
- If an answer says to use defaults (e.g. "use sensible standard defaults"),
  that fact is SETTLED — never ask about it again.
- Be satisfied as soon as a competent CAD modeler could start work. If the
  original request already contains concrete dimensions, be satisfied
  immediately and ask nothing.
- Do not ask about colors, finishes, tolerances, cost, or anything that does
  not change the modeled shape.

Return only JSON:
{
  "satisfied": true | false,
  "question": "the next question to ask ('' when satisfied)",
  "facts": ["concise geometry facts established so far"]
}
"""


class IntakeChatMove(BaseModel):
    """One conversational decision from the intake chatbot."""

    model_config = ConfigDict(extra="forbid")

    satisfied: bool
    question: str = ""
    facts: list[str] = Field(default_factory=list)


class VlmIntakeSummary(BaseModel):
    """Structured summary returned by the intake VLM."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["image", "text"]
    summary: str
    observations: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    # Required-feature checklist — the concrete contract the planner must satisfy
    # and the verifier checks against. object_type is the everyday name of the
    # target ("foldable laptop stand"); required_features are short phrases that
    # each embed a rough proportion/relation ("two tall side frames ~40-60% of
    # base height"). Defaulted so older summaries (and fail-open fallbacks that
    # omit them) still validate.
    object_type: str = ""
    required_features: list[str] = Field(default_factory=list)


def _call_gemini(
    *,
    system_instruction: str,
    parts: list[Any],
    model_env_var: str,
    default_model: str,
    max_output_tokens: int,
    json_response: bool = True,
) -> str:
    """Shared low-level Gemini call for every helper in this module.

    Every caller here needs the same five things: an api-key check, a client,
    a model name resolved from an env var, thinking pinned to LOW (these are
    all mandatory-thinking models — with no output budget the reasoning
    tokens can exhaust the cap before real output is written, the same
    truncation bug class the VLM judge hit: "unterminated JSON object"), and
    the raw response text. Only the instruction/parts/model/budget/response
    format differ per caller, so those are the only parameters.

    Raises RuntimeError if GEMINI_API_KEY is unset; raises whatever the SDK
    raises on a transport/API failure. Callers decide how to handle both —
    some fail open (return a safe default), some let it propagate.
    """
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=os.environ.get(model_env_var, default_model),
        contents=parts,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json" if json_response else None,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
            max_output_tokens=max_output_tokens,
        ),
    )
    return response.text or ""


def summarize_design_request(
    prompt: str,
    image_parts: list[tuple[str, bytes]] | None = None,
) -> dict[str, Any]:
    """Summarize a design request with an optional image reference."""
    from google.genai import types

    parts = [types.Part.from_text(text=f"USER REQUEST:\n{prompt}")]
    for mime_type, data in (image_parts or [])[:3]:
        parts.append(types.Part.from_bytes(data=data, mime_type=mime_type))

    text = _call_gemini(
        system_instruction=INTAKE_INSTRUCTION,
        parts=parts,
        model_env_var="VLM_INTAKE_MODEL",
        default_model="gemini-2.5-pro",
        max_output_tokens=4096,
    )
    return VlmIntakeSummary.model_validate(_read_json(text)).model_dump()


def decide_next_intake_move(
    user_prompt: str,
    intake_summary: dict[str, Any],
    qa_transcript: list[dict[str, str]],
) -> dict[str, Any]:
    """One conversational turn of the intake chatbot.

    Sees the original request, the VLM summary, and the FULL question/answer
    transcript so far, then decides: ask ONE more question, or declare itself
    satisfied. Called once per user message during intake — latency matters, so
    this runs on flash by default (INTAKE_CHAT_MODEL overrides).

    Returns {"satisfied": bool, "question": str, "facts": [str]} (validated).
    """
    from google.genai import types

    transcript = "\n".join(
        f"Q: {item.get('question', '')}\nA: {item.get('answer', '')}"
        for item in qa_transcript
    ) or "(no questions asked yet)"

    text = (
        f"ORIGINAL REQUEST:\n{user_prompt}\n\n"
        f"WHAT THE INTAKE VLM SAW:\n{json.dumps(intake_summary, separators=(',', ':'))}\n\n"
        f"CONVERSATION SO FAR:\n{transcript}\n\n"
        f"Decide: satisfied, or one more question?"
    )

    reply = _call_gemini(
        system_instruction=INTAKE_CHAT_INSTRUCTION,
        parts=[types.Part.from_text(text=text)],
        model_env_var="INTAKE_CHAT_MODEL",
        default_model="gemini-2.5-flash",
        max_output_tokens=2048,
    )
    return IntakeChatMove.model_validate(_read_json(reply)).model_dump()


CLASSIFY_INSTRUCTION = """You classify one chat message sent AFTER a CAD model
has already been generated and is showing in the viewer.

Three categories only:
- "question": the user is asking ABOUT the current model (dimensions, why a
  choice was made, what a feature is) — no geometry change wanted.
- "edit": the user wants the model CHANGED in any way (bigger/smaller, add or
  remove a feature, reposition something, a different count of something).
- "approval": the user is CONFIRMING the current model is correct/good/done — a
  pure positive sign-off with NO change requested ("perfect", "looks good",
  "that's right", "approve this", "yes that's correct", "ship it").

Critical: "approval" requires a PURE positive sign-off. If the message praises
AND asks for any change ("looks good, now make it 2mm bigger"), that is "edit",
not "approval". When genuinely ambiguous between edit and approval, prefer
"edit". When ambiguous between question and edit, prefer "edit" — a message
misread as an edit still lets the user decline the regenerated result, while a
missed edit silently drops a real change request.

Return only JSON: {"kind": "question" | "edit" | "approval"}
"""


class PostDesignClassification(BaseModel):
    """One classification decision for a post-design chat message."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["question", "edit", "approval"]


def classify_post_design_message(user_text: str, plan_summary: str) -> str:
    """Classify a post-design chat message as a question, edit, or approval.

    One cheap flash call, thinking LOW — runs on every message once a design
    is done, so latency matters. Defaults to "edit" on any missing key/model/
    transport error — never "approval", so a transport hiccup can never silently
    record a spurious approval into the flywheel store.
    """
    from google.genai import types

    text = f"CURRENT MODEL:\n{plan_summary}\n\nMESSAGE:\n{user_text}"
    try:
        reply = _call_gemini(
            system_instruction=CLASSIFY_INSTRUCTION,
            parts=[types.Part.from_text(text=text)],
            model_env_var="INTAKE_CHAT_MODEL",
            default_model="gemini-2.5-flash",
            max_output_tokens=256,
        )
        return PostDesignClassification.model_validate(_read_json(reply)).kind
    except Exception:
        return "edit"


ANSWER_INSTRUCTION = """You answer a user's question about a CAD model that has
already been generated. Use ONLY the plan and metrics given — never invent a
dimension or feature not present in them. If the plan/metrics don't contain
the answer, say so plainly instead of guessing. Keep the answer short (2-4
sentences), plain language, no jargon dump.
"""


def answer_model_question(
    question: str,
    plan: dict[str, Any],
    metrics: dict[str, Any] | None = None,
    render_png: str | None = None,
) -> str:
    """Free-form answer about the current model — no geometry regeneration.

    Grounded in the plan JSON + trace metrics (volume, bbox, mesh stats); an
    optional render PNG is attached for visual questions. Raises on transport/
    config failure — unlike the judge/intake helpers, there's no fallback
    verdict to degrade to, so the caller decides how to surface the failure.
    """
    from google.genai import types

    text = (
        f"PLAN:\n{json.dumps(plan, separators=(',', ':'))}\n\n"
        f"METRICS:\n{json.dumps(metrics or {}, separators=(',', ':'))}\n\n"
        f"QUESTION:\n{question}"
    )
    parts = [types.Part.from_text(text=text)]
    if render_png and Path(render_png).exists():
        parts.append(
            types.Part.from_bytes(data=Path(render_png).read_bytes(), mime_type="image/png")
        )

    reply = _call_gemini(
        system_instruction=ANSWER_INSTRUCTION,
        parts=parts,
        model_env_var="INTAKE_CHAT_MODEL",
        default_model="gemini-2.5-flash",
        max_output_tokens=1024,
        json_response=False,
    )
    return reply.strip()


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
