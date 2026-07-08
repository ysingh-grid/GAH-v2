"""Pre-RLM clarification intake for the designs websocket flow.

A real conversational agent: one LLM turn per user message. Each turn the intake
chatbot sees the original request, the VLM's visual summary, and the FULL
question/answer transcript so far, then decides — ask ONE more question, or
declare itself satisfied and hand the gathered facts to the planner. Bounded by
MAX_INTAKE_QUESTIONS so it can never interrogate forever; fails OPEN (straight
to the planner) on any model error.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from tools.vlm_intake import decide_next_intake_move, summarize_design_request

if TYPE_CHECKING:
    from fast_rlm import RLMConfig


_VAGUE_ANSWER_RE = re.compile(
    r"^(?:idk|i\s*don'?t\s*know|not\s*sure|dunno|no\s*idea|any(?:thing)?|whatever|"
    r"standard|sensible|defaults?|use\s+defaults?|use\s+(?:standard|sensible|your)\s+\w+|you\s+(?:decide|choose)|n/?a|-)$",
    re.IGNORECASE,
)
_NUMERIC_HINT_RE = re.compile(r"\d")

# Hard ceiling on back-and-forth rounds. The chatbot is PROMPTED to stop as soon
# as a competent CAD modeler could proceed; this cap is the safety net so a
# model that keeps finding "one more thing" can never trap the user in intake.
MAX_INTAKE_QUESTIONS = 5


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
    """Mutable intake conversation tracked across websocket turns."""

    source: Literal["text", "image"] = "text"
    visual_summary: str = ""
    observations: list[str] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    # Required-feature checklist extracted by the intake VLM (see
    # tools.vlm_intake.VlmIntakeSummary). object_type is the everyday name;
    # required_features are the visible, load-bearing features the planner must
    # build and the verifier will check against.
    object_type: str = ""
    required_features: list[str] = field(default_factory=list)
    answers: list[dict[str, str]] = field(default_factory=list)
    attachment_names: list[str] = field(default_factory=list)
    # The conversational bits: the question currently awaiting the user's reply,
    # how many questions have been asked (bounded by MAX_INTAKE_QUESTIONS), and
    # the chatbot's running list of established geometry facts.
    pending_question: str = ""
    questions_asked: int = 0
    gathered_facts: list[str] = field(default_factory=list)
    # Original VLM summary kept verbatim so every chat turn can re-see it.
    vlm_summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class IntakeOutcome:
    """Outcome of one intake turn."""

    status: Literal["need_user", "ready"]
    question: str = ""
    suggested_options: list[str] = field(default_factory=list)
    state: IntakeState | None = None
    intake_context: str = ""
    feature_checklist: str = ""


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


def _next_move(user_prompt: str, state: IntakeState) -> dict[str, Any]:
    """One chatbot turn: ask another question or declare satisfied.

    Fails OPEN — any model/transport error means "satisfied", so intake can
    never block a design run. The direct Gemini call (flash, thinking LOW) is
    used instead of a fast-rlm run: a chat turn must be fast, and spawning the
    Deno/Pyodide sandbox per websocket message would add seconds of overhead.
    """
    try:
        move = decide_next_intake_move(user_prompt, state.vlm_summary, state.answers)
    except Exception:
        return {"satisfied": True, "question": "", "facts": []}

    question = str(move.get("question") or "").strip()
    if not move.get("satisfied") and not question:
        # A "not satisfied" verdict with no question is unusable — treat as done.
        return {"satisfied": True, "question": "", "facts": move.get("facts") or []}
    return {
        "satisfied": bool(move.get("satisfied")),
        "question": question,
        "facts": [str(f).strip() for f in (move.get("facts") or []) if str(f).strip()],
    }


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
    config: RLMConfig | None,  # kept for call-shape compat; the chatbot is not an RLM run
) -> IntakeOutcome:
    """First user message: summarize the request, then let the chatbot open."""
    _ = config
    try:
        summary = summarize_request_with_vlm(user_prompt, attachments)
    except Exception:
        summary = {
            "mode": "image" if attachments else "text",
            "summary": incoming_text.strip() or user_prompt.strip(),
            "observations": [],
            "missing_facts": [],
        }

    state = IntakeState(
        source="image" if attachments else "text",
        visual_summary=str(summary.get("summary") or "").strip(),
        observations=_clean_summary_values(summary.get("observations")),
        missing_facts=_clean_summary_values(summary.get("missing_facts")),
        object_type=str(summary.get("object_type") or "").strip(),
        required_features=_clean_summary_values(summary.get("required_features")),
        answers=[],
        attachment_names=[attachment.filename for attachment in attachments],
        vlm_summary=dict(summary),
    )

    move = _next_move(user_prompt, state)
    state.gathered_facts = move["facts"] or state.gathered_facts

    if move["satisfied"]:
        # Deterministic backstop: if the chatbot errored out (fail-open path)
        # on a text-only request with no numbers at all, one catch-all question
        # is still better than sending the planner a fully blind prompt.
        if (
            not state.answers
            and not attachments
            and not _NUMERIC_HINT_RE.search(user_prompt or "")
            and not move["facts"]
        ):
            state.pending_question = (
                "What overall size, mounting, material, and any required features should I use?"
            )
            state.questions_asked = 1
            return IntakeOutcome(status="need_user", question=state.pending_question, state=state)
        return IntakeOutcome(
            status="ready",
            intake_context=build_intake_context(user_prompt=user_prompt, state=state),
            feature_checklist=format_feature_checklist(
                state.object_type, state.required_features
            ),
        )

    state.pending_question = move["question"]
    state.questions_asked = 1
    return IntakeOutcome(status="need_user", question=move["question"], state=state)


def _resume_intake(
    *,
    user_prompt: str,
    incoming_text: str,
    state: IntakeState,
) -> IntakeOutcome:
    """Record the user's answer, then let the chatbot ask on or finish."""
    if state.pending_question:
        answer = normalize_clarification_answer(incoming_text)
        state.answers.append(
            {
                "question": state.pending_question,
                "answer": answer or "use sensible standard defaults",
            }
        )
        state.pending_question = ""

    if state.questions_asked >= MAX_INTAKE_QUESTIONS:
        return IntakeOutcome(
            status="ready",
            intake_context=build_intake_context(user_prompt=user_prompt, state=state),
            feature_checklist=format_feature_checklist(
                state.object_type, state.required_features
            ),
        )

    move = _next_move(user_prompt, state)
    if move["facts"]:
        state.gathered_facts = move["facts"]

    if move["satisfied"]:
        return IntakeOutcome(
            status="ready",
            intake_context=build_intake_context(user_prompt=user_prompt, state=state),
            feature_checklist=format_feature_checklist(
                state.object_type, state.required_features
            ),
        )

    state.pending_question = move["question"]
    state.questions_asked += 1
    return IntakeOutcome(status="need_user", question=move["question"], state=state)


def start_or_resume_edit_intake(
    *,
    edit_text: str,
    incoming_text: str,
    plan_summary: str,
    state: IntakeState | None,
) -> IntakeOutcome:
    """Same conversational engine as the pre-planner intake (_next_move), seeded
    to clarify an EDIT to an already-generated model instead of a fresh design.

    No VLM summarization step (there's no fresh image to describe) — the seed is
    built directly from the current plan + the edit request. Ambiguous edits ask
    ONE question at a time, same MAX_INTAKE_QUESTIONS cap as the pre-planner flow.
    `edit_text` stays constant across resumes (the original edit request); only
    `incoming_text` (the reply to whatever question is pending) changes per turn.
    """
    if state is None:
        state = IntakeState(
            source="text",
            visual_summary=plan_summary,
            vlm_summary={
                "mode": "text",
                "summary": (
                    f"Editing an existing model. Current design: {plan_summary}. "
                    f"Requested change: {edit_text}"
                ),
                "observations": [],
                "missing_facts": [],
            },
        )
    elif state.pending_question:
        answer = normalize_clarification_answer(incoming_text)
        state.answers.append({
            "question": state.pending_question,
            "answer": answer or "use sensible standard defaults",
        })
        state.pending_question = ""

    if state.questions_asked >= MAX_INTAKE_QUESTIONS:
        return IntakeOutcome(
            status="ready", intake_context=build_edit_context(edit_text=edit_text, state=state)
        )

    move = _next_move(f"EDIT REQUEST to an existing model: {edit_text}", state)
    if move["facts"]:
        state.gathered_facts = move["facts"]

    if move["satisfied"]:
        return IntakeOutcome(
            status="ready", intake_context=build_edit_context(edit_text=edit_text, state=state)
        )

    state.pending_question = move["question"]
    state.questions_asked += 1
    return IntakeOutcome(status="need_user", question=move["question"], state=state)


def build_edit_context(*, edit_text: str, state: IntakeState) -> str:
    """Build the resolved edit instruction handed to the replanner."""
    lines = [
        "Requested edit to the existing model:",
        f"- edit request: {edit_text.strip()}",
    ]
    if state.gathered_facts:
        lines.append("- clarified facts:")
        lines.extend(f"  - {item}" for item in state.gathered_facts)
    if state.answers:
        lines.append("- clarified answers:")
        lines.extend(_answer_lines(state.answers))
    return "\n".join(lines)


def format_feature_checklist(object_type: str, required_features: list[str]) -> str:
    """Render the required-feature checklist as a compact text block.

    Pure and dependency-free so it can be reused verbatim by the verifier
    (Task 3) and any preview tooling. Returns "" when there is nothing to list,
    so callers can unconditionally concatenate it.
    """
    object_type = (object_type or "").strip()
    features = [f.strip() for f in (required_features or []) if f and f.strip()]
    if not object_type and not features:
        return ""
    lines = ["Required-feature checklist:"]
    if object_type:
        lines.append(f"- target object: {object_type}")
    for feat in features:
        lines.append(f"- [ ] {feat}")
    return "\n".join(lines)


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
    if state.gathered_facts:
        lines.append("- established facts:")
        lines.extend(f"  - {item}" for item in state.gathered_facts)
    if state.missing_facts:
        lines.append("- still missing:")
        lines.extend(f"  - {item}" for item in state.missing_facts)
    if state.answers:
        lines.append("- clarified answers:")
        lines.extend(_answer_lines(state.answers))
    checklist = format_feature_checklist(state.object_type, state.required_features)
    if checklist:
        lines.append("")
        lines.append(checklist)
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
