"""Data models for the designs service.

A DesignSession holds the full state of one user chat → CAD part conversation.
It lives in memory (store.py) and is serialized to JSON for the HTTP GET and WS
events. Status transitions:

  chatting → generating → done
                       ↘ failed
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from backend.designs.intake import IntakeState

DesignStatus = Literal["chatting", "generating", "done", "failed", "needs_user"]


@dataclass
class DesignSession:
    """One user-to-part conversation."""

    id: str
    status: DesignStatus
    original_prompt: str
    history: list[dict[str, str]]  # [{"role": "user"|"planner", "content": str}]
    intake_state: IntakeState | None = None
    intake_context: str = ""
    # Required-feature checklist text (Task 2) captured at intake, threaded to the
    # geometry loop so the verifier judges the render per-feature. Persists across
    # edits so later runs stay grounded.
    feature_checklist: str = ""
    last_plan: dict[str, Any] | None = None
    run_id: str | None = None
    # Set while a post-design EDIT request is being clarified (reuses
    # intake_state for the Q&A round-trip, same as the pre-planner intake).
    # Empty = not currently clarifying an edit. Distinguishes a "needs_user"
    # caused by an edit clarification from one caused by the original intake.
    pending_edit_text: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "original_prompt": self.original_prompt,
            "history": self.history,
            "intake_state": asdict(self.intake_state) if self.intake_state else None,
            "intake_context": self.intake_context,
            "feature_checklist": self.feature_checklist,
            "last_plan": self.last_plan,
            "run_id": self.run_id,
            "pending_edit_text": self.pending_edit_text,
            "created_at": self.created_at,
        }


def new_session() -> DesignSession:
    return DesignSession(
        id=uuid.uuid4().hex,
        status="chatting",
        original_prompt="",
        history=[],
        intake_state=None,
        intake_context="",
    )
