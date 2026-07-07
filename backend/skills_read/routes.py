from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from . import store

router = APIRouter()


@router.get("/internal/list-skills")
def list_skills() -> list[str]:
    """Planner's guide catalog (SKILLS.md) — replan-only guides not listed."""
    return store.load_planner_skills()


@router.get("/internal/list-skills-replan")
def list_skills_replan() -> list[str]:
    """Replanner's guide catalog (SKILLS_replan.md) — planner-only guides not listed."""
    return store.load_replan_skills()


@router.get("/internal/read-skill", response_class=PlainTextResponse)
def read_skill(name: str) -> str:
    try:
        return store.read_skill(name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
