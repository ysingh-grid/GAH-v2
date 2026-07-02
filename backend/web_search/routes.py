"""HTTP layer for the web-search service. Thin handler over store.py."""

from fastapi import APIRouter

from . import store

router = APIRouter()


@router.get("/internal/web-search")
def web_search(q: str) -> dict:
    """Grounded web search for a measurement/standard. Returns query/answer/sources."""
    return store.search_measurements(q)
