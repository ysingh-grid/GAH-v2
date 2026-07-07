"""Run trace + the 6-category failure taxonomy (PRD §14).

Every design attempt — pass or fail — produces an auditable trace JSON in the
run's artifact folder. Failures MUST carry one of the six canonical root-cause
categories so the "0 silent geometry failures" gate (PRD §11) holds: every
failure lands in a category, never a generic "Error".
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from tools.artifacts import run_dir


class FailureCategory(StrEnum):
    """The six canonical root causes a failed attempt is tagged with (PRD §14)."""

    primitive_gap = "primitive_gap"  # library can't express the geometry
    geometry_invalidity = "geometry_invalidity"  # compile/exec/mesh produced invalid geometry
    visual_mismatch = "visual_mismatch"  # verifier says it doesn't match intent
    translation_drift = "translation_drift"  # reserved (was forge.js drift; forge path removed — no stage maps to it now)
    verifier_miss = "verifier_miss"  # verifier itself failed/erred
    user_ambiguity = "user_ambiguity"  # intent underspecified; needs the human


# Loop stage -> the failure category it maps to when that stage fails.
STAGE_TO_CATEGORY: dict[str, FailureCategory] = {
    "cadquery_compile": FailureCategory.geometry_invalidity,
    "cadquery_execute": FailureCategory.geometry_invalidity,
    "mesh_repair": FailureCategory.geometry_invalidity,
    "visual_mismatch": FailureCategory.visual_mismatch,
    "primitive_gap": FailureCategory.primitive_gap,
    "verifier_error": FailureCategory.verifier_miss,
    "user_ambiguity": FailureCategory.user_ambiguity,
}


def category_for_stage(stage: str) -> FailureCategory:
    """Map a loop failure stage to its canonical taxonomy category."""
    return STAGE_TO_CATEGORY.get(stage, FailureCategory.geometry_invalidity)


def build_trace(
    *,
    run_id: str,
    prompt: str,
    plan: dict[str, Any] | None,
    code: str | None,
    execution_result: dict[str, Any] | None,
    mesh_report: dict[str, Any] | None,
    renders: dict[str, Any] | None,
    verdict: dict[str, Any] | None,
    status: str,
    attempts: int,
    failure_category: FailureCategory | None,
    failure_detail: str | None = None,
    duration_s: float | None = None,
) -> dict[str, Any]:
    """Assemble the full trace payload for one attempt (pure, no I/O).

    `status` is "success" | "failed". A non-success status MUST carry a
    `failure_category`; this is asserted so a failure can never slip through
    uncategorised. `duration_s` is the measured workflow wall-clock (seconds)
    for the "<5 min single-part workflow time" gate (PRD §Decision Metrics).
    """
    if status != "success" and failure_category is None:
        raise ValueError(f"status '{status}' requires a failure_category (PRD §14)")

    from datetime import UTC, datetime

    return {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "prompt": prompt,
        "plan": plan,
        "code": code,
        "execution_result": execution_result,
        "mesh_report": mesh_report,
        "renders": renders,
        "verdict": verdict,
        "outcome": {
            "status": status,
            "attempts": attempts,
            "duration_s": duration_s,
            "failure_category": failure_category.value if failure_category else None,
            "failure_detail": failure_detail,
        },
    }


def write_trace(trace: dict[str, Any]) -> str:
    """Write a trace payload to outputs/{run_id}/trace.json; return its path."""
    run_id = trace["run_id"]
    path = run_dir(run_id) / "trace.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trace, f, indent=2)
    return str(path)
