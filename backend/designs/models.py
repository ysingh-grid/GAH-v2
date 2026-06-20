"""Data models for the designs service.

A DesignSession holds the full state of one user chat → CAD part conversation.
It lives in memory (store.py) and is serialized to JSON for the HTTP GET and WS
events. Status transitions:

  chatting → generating → done
                       ↘ failed
                       ↘ needs_user → (user answers) → generating → ...
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

DesignStatus = Literal["chatting", "generating", "done", "failed", "needs_user"]


@dataclass
class DesignSession:
    """One user-to-part conversation."""

    id: str
    status: DesignStatus
    original_prompt: str
    history: list[dict[str, str]]  # [{"role": "user"|"planner", "content": str}]
    last_plan: dict[str, Any] | None = None
    forge_js: str | None = None
    run_id: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "original_prompt": self.original_prompt,
            "history": self.history,
            "last_plan": self.last_plan,
            "forge_js": self.forge_js,
            "run_id": self.run_id,
            "created_at": self.created_at,
        }


def new_session() -> DesignSession:
    return DesignSession(
        id=uuid.uuid4().hex,
        status="chatting",
        original_prompt="",
        history=[],
    )
