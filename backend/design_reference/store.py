"""Data access for the design-reference catalog (fastener dims + recipes).

The ONLY place that reads primitives/design_reference.json. Exposed as an
index/fetch pair (mirroring backend/kb_read) so the planner sees a compact menu
of reusable references and pulls only the entries it needs — instead of the
whole file. The index/fetch MERGE the runtime approved-designs store
(backend/approved_store), so past USER-APPROVED full designs appear as reference
keys (`approved__*`) alongside the curated recipes and dimension tables.
"""

import json
from pathlib import Path

from backend.approved_store import store as approved_store

# store.py -> design_reference -> backend -> repo root, then primitives/.
_REFERENCE_PATH = Path(__file__).resolve().parents[2] / "primitives" / "design_reference.json"

_FASTENER_KEY = "fastener_dims"


def _load() -> dict:
    """Load the whole design-reference document (raises if missing)."""
    with _REFERENCE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def index_reference() -> dict[str, str]:
    """Compact menu of every reusable reference as {key: one-line description}.

    Covers the curated CSG recipes, the always-useful `fastener_dims` tables, and
    (merged in) the newest USER-APPROVED past designs from the approved store.
    This is the INDEX, not the content — the planner reads it, picks keys, then
    calls fetch_reference() for just those.
    """
    doc = _load()
    idx: dict[str, str] = {
        name: str(r.get("description", ""))[:140]
        for name, r in doc.get("recipes", {}).items()
    }
    idx[_FASTENER_KEY] = "metric fastener clearance / tap / counterbore dimension tables"
    idx.update(approved_store.index_approved())  # past approved designs
    return idx


def fetch_reference(keys: list[str]) -> dict[str, dict]:
    """Fetch specific references by key from index_reference().

    Recipe keys return {description, keywords, steps}; `fastener_dims` returns the
    dimension tables; `approved__*` keys delegate to the approved store and return
    {description, original_prompt, steps}. Unknown keys are silently omitted.
    """
    doc = _load()
    recipes: dict = doc.get("recipes", {})
    out: dict[str, dict] = {}
    for key in keys:
        if key == _FASTENER_KEY:
            out[key] = doc.get("fastener_dims", {})
        elif key in recipes:
            out[key] = recipes[key]
    out.update(approved_store.fetch_approved(keys))
    return out
