"""HTTP layer for the design-reference service. Thin handlers over store.py.

Two endpoints mirroring the KB pattern (index → fetch):
  GET /internal/design-reference/index          → menu of reusable references.
  GET /internal/design-reference/fetch?keys=... → fetch specific entries by key.

Both merge the runtime approved-designs store, so past USER-APPROVED designs
appear as `approved__*` keys alongside the curated recipes and fastener tables.
"""

from fastapi import APIRouter

from . import store

router = APIRouter()


@router.get("/internal/design-reference/index")
def design_reference_index() -> dict:
    """Return the compact index of available references as {key: description}."""
    return store.index_reference()


@router.get("/internal/design-reference/fetch")
def design_reference_fetch(keys: str) -> dict:
    """Fetch specific references by comma-separated keys from the index.

    Args (query param):
        keys: Comma-separated keys, e.g. "bolt_circle,fastener_dims,approved__design_x".

    Returns:
        {key: entry} for each found key. Missing keys are silently omitted.
    """
    key_list = [k.strip() for k in keys.split(",") if k.strip()]
    return store.fetch_reference(key_list)
