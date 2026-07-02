"""Pre-RLM clarification intake for the designs websocket flow."""

from __future__ import annotations

import base64
import copy
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tools.vlm_intake import summarize_design_request

if TYPE_CHECKING:
    from fast_rlm import RLMConfig


_VAGUE_ANSWER_RE = re.compile(
    r"^(?:idk|i\s*don'?t\s*know|not\s*sure|dunno|no\s*idea|any(?:thing)?|whatever|"
    r"standard|sensible|defaults?|use\s+defaults?|use\s+(?:standard|sensible|your)\s+\w+|you\s+(?:decide|choose)|n/?a|-)$",
    re.IGNORECASE,
)
_NUMERIC_HINT_RE = re.compile(r"\d")

_INTAKE_ROLE = (
    "You help a CAD planner ask only the few non-negotiable clarification "
    "questions needed before geometry generation. Use plain language, avoid "
    "jargon, and ask at most 3 short questions. Focus on overall size, count "
    "of repeated features, critical orientation/mounting, and material only if "
    "it changes the shape. If the request is already specific enough, return "
    "no questions."
)


class ClarificationQuestions(BaseModel):
    """Structured question list returned by the intake LLM."""

    model_config = ConfigDict(extra="forbid")

    questions: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class IncomingAttachment:
    """A websocket attachment payload normalized for VLM intake."""

    filename: str
    mime_type: str
    data_b64: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> IncomingAttachment | None:
        """Build an attachment from a websocket payload dict."""
        mime_type = str(payload.get("mime_type") or payload.get("mimeType") or "").strip()
        if not mime_type.startswith("image/"):
            return None

        filename = str(payload.get("filename") or payload.get("name") or "image").strip()
        data_b64 = str(
            payload.get("data")
            or payload.get("base64")
            or payload.get("content")
            or payload.get("data_b64")
            or ""
        ).strip()
        if data_b64.startswith("data:") and "," in data_b64:
            data_b64 = data_b64.split(",", 1)[1].strip()
        if not data_b64:
            return None
        return cls(filename=filename or "image", mime_type=mime_type, data_b64=data_b64)

    def to_bytes(self) -> bytes:
        """Decode the attachment into raw bytes."""
        normalized = self.data_b64.replace("\n", "").replace(" ", "")
        padding = (-len(normalized)) % 4
        if padding:
            normalized += "=" * padding
        return base64.b64decode(normalized)


@dataclass
class IntakeState:
    """Mutable intake progress tracked across websocket turns."""

    source: Literal["text", "image"] = "text"
    visual_summary: str = ""
    observations: list[str] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    question_queue: list[str] = field(default_factory=list)
    answers: list[dict[str, str]] = field(default_factory=list)
    attachment_names: list[str] = field(default_factory=list)
    active_question_index: int = 0


@dataclass
class IntakeOutcome:
    """Outcome of one intake turn."""

    status: Literal["need_user", "ready"]
    question: str = ""
    suggested_options: list[str] = field(default_factory=list)
    state: IntakeState | None = None
    intake_context: str = ""


def normalize_clarification_answer(answer: str | None) -> str | None:
    """Normalize free-form clarification answers to a deterministic form."""
    cleaned = (answer or "").strip()
    if not cleaned:
        return None
    if _VAGUE_ANSWER_RE.match(cleaned):
        return "use sensible standard defaults"
    return cleaned


def parse_incoming_attachments(
    raw_attachments: list[dict[str, Any]] | None,
) -> list[IncomingAttachment]:
    """Keep only image attachments from the websocket payload."""
    attachments: list[IncomingAttachment] = []
    for payload in raw_attachments or []:
        if not isinstance(payload, dict):
            continue
        attachment = IncomingAttachment.from_payload(payload)
        if attachment is not None:
            attachments.append(attachment)
    return attachments


def summarize_request_with_vlm(
    user_prompt: str,
    attachments: list[IncomingAttachment],
) -> dict[str, Any]:
    """Summarize the request using the vision-language intake model."""
    image_parts = [(attachment.mime_type, attachment.to_bytes()) for attachment in attachments]
    return summarize_design_request(user_prompt, image_parts=image_parts or None)


def generate_clarification_questions(
    user_prompt: str,
    intake_summary: dict[str, Any],
    *,
    config: RLMConfig | None = None,
) -> list[str]:
    """Generate up to three clarifying questions from the intake summary."""
    import fast_rlm

    if config is None:
        from rlm.rlm_config import config as default_config

        config = default_config

    clar_cfg = copy.copy(config)
    clar_cfg.max_depth = 0
    clar_cfg.max_calls_per_subagent = 1

    try:
        result = fast_rlm.run(
            {
                "task": "Generate concise clarification questions for a CAD request.",
                "user_prompt": user_prompt,
                "intake_summary": intake_summary,
                "role_instructions": _INTAKE_ROLE,
            },
            prefix="clarifier",
            config=clar_cfg,
            tools=[],
            output_schema=ClarificationQuestions,
            verbose=False,
        )
        questions = ClarificationQuestions.model_validate(result["results"]).questions
    except Exception:
        questions = []

    return [question.strip() for question in questions if (question or "").strip()][:3]


def start_or_resume_intake(
    *,
    user_prompt: str,
    incoming_text: str,
    attachments: list[IncomingAttachment],
    state: IntakeState | None,
    config: RLMConfig | None = None,
) -> IntakeOutcome:
    """Advance the intake state machine by one websocket turn."""
    if state is None:
        return _start_new_intake(
            user_prompt=user_prompt,
            incoming_text=incoming_text,
            attachments=attachments,
            config=config,
        )
    return _resume_intake(user_prompt=user_prompt, incoming_text=incoming_text, state=state)


def build_planner_history(
    *,
    original_prompt: str,
    chat_history: list[dict[str, str]],
    intake_context: str,
) -> list[dict[str, str]]:
    """Inject the intake context into the chat history for the RLM."""
    if not intake_context:
        return list(chat_history)

    history = list(chat_history)

    # Inject directly into the latest user message to avoid 'system' role rejection
    # by the Gemini API, and guarantee it acts as immutable context for the planner.
    if history and history[-1]["role"] == "user":
        history[-1] = {
            "role": "user",
            "content": f"{history[-1]['content']}\n\n{intake_context}"
        }
    else:
        history.append({
            "role": "user",
            "content": f"Please incorporate these established facts:\n\n{intake_context}"
        })
    return history


def _start_new_intake(
    *,
    user_prompt: str,
    incoming_text: str,
    attachments: list[IncomingAttachment],
    config: RLMConfig | None,
) -> IntakeOutcome:
    """Start intake from the user's initial request."""
    try:
        summary = summarize_request_with_vlm(user_prompt, attachments)
    except Exception:
        summary = {
            "mode": "image" if attachments else "text",
            "summary": incoming_text.strip() or user_prompt.strip(),
            "observations": [],
            "missing_facts": [],
        }

    questions = _generate_questions_with_fallback(user_prompt, summary, attachments, config=config)
    state = IntakeState(
        source="image" if attachments else "text",
        visual_summary=str(summary.get("summary") or "").strip(),
        observations=_clean_summary_values(summary.get("observations")),
        missing_facts=_clean_summary_values(summary.get("missing_facts")),
        question_queue=questions,
        answers=[],
        attachment_names=[attachment.filename for attachment in attachments],
        active_question_index=0,
    )

    if questions:
        return IntakeOutcome(status="need_user", question=questions[0], state=state)

    return IntakeOutcome(
        status="ready",
        intake_context=build_intake_context(user_prompt=user_prompt, state=state),
    )


def _resume_intake(
    *,
    user_prompt: str,
    incoming_text: str,
    state: IntakeState,
) -> IntakeOutcome:
    """Record one answer and either ask the next question or finish intake."""
    if not state.question_queue:
        return IntakeOutcome(
            status="ready",
            intake_context=build_intake_context(user_prompt=user_prompt, state=state),
        )

    current_question = state.question_queue[state.active_question_index]
    answer = normalize_clarification_answer(incoming_text)
    state.answers.append(
        {
            "question": current_question,
            "answer": answer or "use sensible standard defaults",
        }
    )
    state.active_question_index += 1

    if state.active_question_index < len(state.question_queue):
        next_question = state.question_queue[state.active_question_index]
        return IntakeOutcome(status="need_user", question=next_question, state=state)

    return IntakeOutcome(
        status="ready",
        intake_context=build_intake_context(user_prompt=user_prompt, state=state),
    )


def _generate_questions_with_fallback(
    user_prompt: str,
    summary: dict[str, Any],
    attachments: list[IncomingAttachment],
    *,
    config: RLMConfig | None,
) -> list[str]:
    """Generate questions and apply a conservative fallback for under-specified text."""
    questions = generate_clarification_questions(user_prompt, summary, config=config)
    if questions:
        return questions

    if attachments or _NUMERIC_HINT_RE.search(user_prompt or ""):
        return []

    return [
        "What overall size, mounting, material, and any required features should I use?"
    ]


def build_intake_context(user_prompt: str, state: IntakeState) -> str:
    """Build the text block handed to the planner as immutable intake facts."""
    lines = [
        "Pre-planner intake facts:",
        f"- original request: {user_prompt.strip()}",
        f"- input mode: {state.source}",
        f"- visual summary: {state.visual_summary or 'n/a'}",
    ]
    if state.attachment_names:
        lines.append(f"- attachments: {', '.join(state.attachment_names)}")
    if state.observations:
        lines.append("- observations:")
        lines.extend(f"  - {item}" for item in state.observations)
    if state.missing_facts:
        lines.append("- still missing:")
        lines.extend(f"  - {item}" for item in state.missing_facts)
    if state.answers:
        lines.append("- clarified answers:")
        lines.extend(_answer_lines(state.answers))
    return "\n".join(lines)


def _clean_summary_values(values: list[object] | None) -> list[str]:
    """Trim and drop empty values from VLM summary lists."""
    cleaned: list[str] = []
    for item in values or []:
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _answer_lines(answers: list[dict[str, str]]) -> list[str]:
    """Format clarification answers for the planner context."""
    return [
        f"  - {item['question']} -> {item['answer']}"
        for item in answers
        if item.get("question")
    ]
