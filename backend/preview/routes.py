"""HTTP layer for the preview service. Thin handler over store.preview_plan."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from . import store

router = APIRouter()


class PreviewRequest(BaseModel):
    """Body for POST /internal/preview-plan."""

    plan: dict[str, Any]
    feature_checklist: str = ""
    # VLM critique renders + judges the preview — real cost, so it is opt-in.
    critique: bool = Field(default=False)


@router.post("/internal/preview-plan")
def preview_plan(req: PreviewRequest) -> dict[str, Any]:
    """Compile + execute + inspect a candidate plan; return real-geometry evidence.

    Never raises on a bad plan — a malformed/uncompilable/failing plan comes back
    as evidence with compiles/executes flags + an error string, which is exactly
    what the planner needs to self-correct.
    """
    return store.preview_plan(
        req.plan, feature_checklist=req.feature_checklist, critique=req.critique
    )
