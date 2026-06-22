"""Data access for the design-reference catalog (fastener dims + recipes).

The ONLY place that reads primitives/design_reference.json. A keyword query
returns the matching recipe templates plus the always-useful fastener dimension
tables, kept compact so a planner call never balloons the token budget.
"""

import json
from pathlib import Path

# store.py -> design_reference -> backend -> repo root, then primitives/.
_REFERENCE_PATH = Path(__file__).resolve().parents[2] / "primitives" / "design_reference.json"


def _load() -> dict:
    """Load the whole design-reference document (raises if missing)."""
    with _REFERENCE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def search_reference(query: str, max_recipes: int = 3) -> dict:
    """Return fastener dims + recipe templates relevant to a keyword query.

    Args:
        query: Free-text hint, e.g. "M6 counterbored bolt holes on a flange".
        max_recipes: Cap on returned recipes (token hygiene; default 3).

    Returns:
        {"fastener_dims": {...}, "recipes": {name: {...}}}. Recipes are scored by
        keyword overlap with the query; the fastener tables are always included
        because dimensions are useful for nearly every metal part.
    """
    doc = _load()
    fastener_dims = doc.get("fastener_dims", {})
    all_recipes: dict = doc.get("recipes", {})

    q_words = {w.strip(".,/()").lower() for w in query.split() if w.strip()}

    def score(recipe: dict) -> int:
        kws = {k.lower() for k in recipe.get("keywords", [])}
        # +2 per exact keyword hit, +1 for any query word appearing in a keyword.
        hits = sum(2 for k in kws if k in q_words)
        hits += sum(1 for k in kws for w in q_words if w in k)
        return hits

    ranked = sorted(all_recipes.items(), key=lambda kv: score(kv[1]), reverse=True)
    # Keep only positively-scored recipes; if nothing matches, return none (the
    # planner still gets the dims and can proceed with raw primitives).
    chosen = {name: r for name, r in ranked[:max_recipes] if score(r) > 0}

    return {"fastener_dims": fastener_dims, "recipes": chosen}
