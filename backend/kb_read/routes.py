"""HTTP layer for the KB retrieval service (FastAPI). Thin handlers over store.py.

Two endpoints mirroring the primitives pattern (list → lookup):
  GET /internal/kb-index          → compact menu of what's available in both KBs.
  GET /internal/kb-fetch?keys=... → fetch specific sections by slug key.
"""

from fastapi import APIRouter

from . import store

router = APIRouter()


@router.get("/internal/kb-index")
def kb_index() -> dict[str, dict[str, str]]:
    """Return the compact index of available KB sections (CadQuery + ForgeCAD).

    Returns:
        {"cadquery": {slug: description}, "forgecad": {slug: description}}
    """
    return store.list_kb_index()


@router.get("/internal/kb-fetch")
def kb_fetch(keys: str) -> dict[str, str]:
    """Fetch specific KB sections by comma-separated slug keys.

    Args (query param):
        keys: Comma-separated slugs from kb-index, e.g.
              "3d-operations,revolve,sweep,fillet-and-chamfer".

    Returns:
        {slug: content_snippet} for each found key (≤800 chars each).
        Missing keys are silently omitted.
    """
    key_list = [k.strip() for k in keys.split(",") if k.strip()]
    return store.fetch_kb_sections(key_list)
