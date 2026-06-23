"""HTTP layer for the primitives service (FastAPI). Thin handlers over store.py."""

from fastapi import APIRouter, HTTPException

from . import store

router = APIRouter()


@router.get("/internal/get-primitives")
def get_primitives() -> dict:
    """Return all available primitives with templates and verification stripped."""
    return store.get_primitives_for_agent()

