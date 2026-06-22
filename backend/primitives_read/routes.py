"""HTTP layer for the primitives service (FastAPI). Thin handlers over store.py."""

from fastapi import APIRouter, HTTPException

from . import store

router = APIRouter()


@router.get("/internal/list-primitives")
def list_primitives() -> dict:
    """Return the full primitive catalog as JSON."""
    return store.load_all_primitives()


@router.get("/internal/lookup-primitive")
def lookup_primitive(key: str) -> dict:
    """Return one primitive spec by name. 404 if the primitive is unknown."""
    try:
        return store.get_primitive(key)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
