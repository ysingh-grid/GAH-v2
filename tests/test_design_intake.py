"""Tests for the pre-RLM intake flow."""

from __future__ import annotations

from unittest.mock import patch

from backend.designs.intake import (
    IncomingAttachment,
    IntakeState,
    build_planner_history,
    normalize_clarification_answer,
    start_or_resume_intake,
)


def test_normalize_clarification_answer_maps_vague_answers_to_defaults() -> None:
    assert normalize_clarification_answer("  use defaults  ") == "use sensible standard defaults"
    assert normalize_clarification_answer("not sure") == "use sensible standard defaults"
    assert normalize_clarification_answer("") is None
    assert normalize_clarification_answer("30 mm") == "30 mm"


@patch("backend.designs.intake.generate_clarification_questions")
@patch("backend.designs.intake.summarize_request_with_vlm")
def test_start_or_resume_intake_asks_for_clarification_on_first_turn(
    mock_summarize,
    mock_questions,
) -> None:
    mock_summarize.return_value = {
        "mode": "image",
        "summary": "A bracket with a central opening and two side ears.",
        "observations": ["side ears are visible"],
        "missing_facts": ["overall size", "mounting hole diameter"],
    }
    mock_questions.return_value = [
        "How big should it be overall?",
        "What diameter should the mounting hole be?",
    ]

    outcome = start_or_resume_intake(
        user_prompt="make this bracket",
        incoming_text="make this bracket",
        attachments=[
            IncomingAttachment(
                filename="bracket.png",
                mime_type="image/png",
                data_b64="ZmFrZQ==",
            )
        ],
        state=None,
    )

    assert outcome.status == "need_user"
    assert outcome.question == "How big should it be overall?"
    assert outcome.state is not None
    assert outcome.state.question_queue == [
        "How big should it be overall?",
        "What diameter should the mounting hole be?",
    ]
    assert outcome.state.attachment_names == ["bracket.png"]


def test_start_or_resume_intake_builds_context_after_final_answer() -> None:
    state = IntakeState(
        source="text",
        visual_summary="A plain box-like enclosure.",
        question_queue=["How wide should it be?", "How tall should it be?"],
        answers=[{"question": "How wide should it be?", "answer": "120 mm"}],
        attachment_names=[],
        active_question_index=1,
    )

    outcome = start_or_resume_intake(
        user_prompt="make an enclosure",
        incoming_text="80 mm",
        attachments=[],
        state=state,
    )

    assert outcome.status == "ready"
    assert "visual summary" in outcome.intake_context
    assert "How wide should it be?" in outcome.intake_context
    assert "120 mm" in outcome.intake_context
    assert "How tall should it be?" in outcome.intake_context
    assert "80 mm" in outcome.intake_context

    history = build_planner_history(
        original_prompt="make an enclosure",
        chat_history=[{"role": "user", "content": "make an enclosure"}],
        intake_context=outcome.intake_context,
    )
    assert history[-1]["role"] == "system"
    assert "pre-planner intake" in history[-1]["content"].lower()
