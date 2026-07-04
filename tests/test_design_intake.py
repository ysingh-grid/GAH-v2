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


@patch("backend.designs.intake.decide_next_intake_move")
@patch("backend.designs.intake.summarize_request_with_vlm")
def test_start_or_resume_intake_asks_for_clarification_on_first_turn(
    mock_summarize,
    mock_move,
) -> None:
    mock_summarize.return_value = {
        "mode": "image",
        "summary": "A bracket with a central opening and two side ears.",
        "observations": ["side ears are visible"],
        "missing_facts": ["overall size", "mounting hole diameter"],
    }
    mock_move.return_value = {
        "satisfied": False,
        "question": "How big should it be overall?",
        "facts": ["bracket with two side ears"],
    }

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
    assert outcome.state.pending_question == "How big should it be overall?"
    assert outcome.state.questions_asked == 1
    assert outcome.state.attachment_names == ["bracket.png"]


@patch("backend.designs.intake.decide_next_intake_move")
def test_intake_chatbot_goes_back_and_forth_until_satisfied(mock_move) -> None:
    """The chatbot decides each turn: keep asking (informed by all answers so
    far) or stop — no fixed upfront question list."""
    state = IntakeState(
        source="text",
        visual_summary="A plain box-like enclosure.",
        pending_question="How wide should it be?",
        questions_asked=1,
        vlm_summary={"summary": "A plain box-like enclosure."},
    )

    # Turn 1: user answers width; chatbot wants one more thing.
    mock_move.return_value = {
        "satisfied": False,
        "question": "How tall should it be?",
        "facts": ["width 120mm"],
    }
    outcome = start_or_resume_intake(
        user_prompt="make an enclosure",
        incoming_text="120 mm",
        attachments=[],
        state=state,
    )
    assert outcome.status == "need_user"
    assert outcome.question == "How tall should it be?"
    # The chatbot saw the FULL transcript, including the answer just given.
    transcript_arg = mock_move.call_args.args[2]
    assert transcript_arg[-1] == {"question": "How wide should it be?", "answer": "120 mm"}

    # Turn 2: user answers height; chatbot is satisfied.
    mock_move.return_value = {
        "satisfied": True,
        "question": "",
        "facts": ["width 120mm", "height 80mm"],
    }
    outcome = start_or_resume_intake(
        user_prompt="make an enclosure",
        incoming_text="80 mm",
        attachments=[],
        state=outcome.state,
    )
    assert outcome.status == "ready"
    assert "How wide should it be?" in outcome.intake_context
    assert "120 mm" in outcome.intake_context
    assert "How tall should it be?" in outcome.intake_context
    assert "80 mm" in outcome.intake_context
    assert "height 80mm" in outcome.intake_context  # gathered facts included

    history = build_planner_history(
        original_prompt="make an enclosure",
        chat_history=[{"role": "user", "content": "make an enclosure"}],
        intake_context=outcome.intake_context,
    )
    assert history[-1]["role"] == "user"
    assert "pre-planner intake" in history[-1]["content"].lower()


@patch("backend.designs.intake.decide_next_intake_move")
def test_intake_stops_at_question_cap_even_if_chatbot_wants_more(mock_move) -> None:
    """MAX_INTAKE_QUESTIONS is a hard ceiling — an over-curious model can never
    trap the user in an endless interview."""
    from backend.designs.intake import MAX_INTAKE_QUESTIONS

    mock_move.return_value = {
        "satisfied": False,
        "question": "And one more thing?",
        "facts": [],
    }
    state = IntakeState(
        source="text",
        visual_summary="A widget.",
        pending_question="Question at the cap?",
        questions_asked=MAX_INTAKE_QUESTIONS,
        vlm_summary={},
    )

    outcome = start_or_resume_intake(
        user_prompt="make a widget",
        incoming_text="whatever",
        attachments=[],
        state=state,
    )
    assert outcome.status == "ready"  # forced done, chatbot not even consulted
    assert "use sensible standard defaults" in outcome.intake_context


@patch("backend.designs.intake.decide_next_intake_move")
@patch("backend.designs.intake.summarize_request_with_vlm")
def test_intake_fails_open_when_chat_model_errors(mock_summarize, mock_move) -> None:
    """A model/transport error must never block a run — intake passes through
    (with the deterministic catch-all only for blind text-only prompts)."""
    mock_summarize.return_value = {
        "mode": "text",
        "summary": "A 60mm cube.",
        "observations": [],
        "missing_facts": [],
    }
    mock_move.side_effect = RuntimeError("gemini down")

    outcome = start_or_resume_intake(
        user_prompt="make a 60mm cube",  # has digits -> no catch-all
        incoming_text="make a 60mm cube",
        attachments=[],
        state=None,
    )
    assert outcome.status == "ready"
