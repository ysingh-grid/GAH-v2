"""Shared dataclasses passed between the Temporal workflow and its activities.

Must be JSON-serialisable (Temporal's default codec is JSON).
Plain dataclasses with primitive fields satisfy this requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DesignInput:
    """Everything the DesignWorkflow needs to produce a part."""

    original_prompt: str
    # PrimitivePlan serialised via runtime.schema.plan_to_dict() — JSON-safe.
    plan_dict: dict[str, Any]
    run_id: str
    backend_url: str = "http://localhost:8001"


@dataclass
class DesignResult:
    """Outcome returned by the DesignWorkflow to the workflow starter."""

    status: str  # "success" | "failed" | "needs_user"
    forge_js: str = ""
    final_plan: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    failure_category: str = ""
    message: str = ""
    question: str = ""
