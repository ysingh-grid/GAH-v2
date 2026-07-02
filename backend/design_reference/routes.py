"""HTTP layer for the design-reference service. Thin handler over store.py."""

from fastapi import APIRouter

from . import store

router = APIRouter()


@router.get("/internal/design-reference")
def design_reference(q: str) -> dict:
    """Return fastener dims + recipe templates relevant to query `q`."""
    return store.search_reference(q)
