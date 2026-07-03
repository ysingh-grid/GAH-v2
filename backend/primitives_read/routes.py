"""HTTP layer for the primitives service (FastAPI). Thin handlers over store.py."""

from fastapi import APIRouter, HTTPException

from . import store

router = APIRouter()


@router.get("/internal/get-primitives")
def get_primitives() -> dict:
    """Return all available primitives with templates and verification stripped."""
    return store.get_primitives_for_agent()


@router.get("/internal/list-primitives")
def list_primitives() -> dict:
    """Return the primitive menu expected by the RLM pull tools."""
    return store.get_primitives_for_agent()


@router.get("/internal/lookup-primitive")
def lookup_primitive(key: str) -> dict:
    """Return one full primitive spec for the RLM pull tools."""
    try:
        return store.get_primitive(key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
