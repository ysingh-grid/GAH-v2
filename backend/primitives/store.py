"""Data access for the primitive catalog. Reads primitives/library.json from disk.

This is the ONLY place that touches library.json. Routes call these functions;
they never read the file themselves. Each function does exactly one thing.
"""

import json
from pathlib import Path

# Repo root is three parents up: store.py -> primitives -> backend -> repo root.
_LIBRARY_PATH = Path(__file__).resolve().parents[2] / "primitives" / "library.json"


def load_all_primitives() -> dict:
    """Load the entire primitive catalog.

    Returns:
        A dict mapping each primitive name to its spec
        (description, parameters, verification, template).

    Raises:
        FileNotFoundError: if library.json is missing.
    """
    with _LIBRARY_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def get_primitive(key: str) -> dict:
    """Look up a single primitive's spec by name.

    Args:
        key: The primitive name, e.g. "box" or "hexagon_prism".

    Returns:
        The spec dict for that primitive.

    Raises:
        KeyError: if the primitive name is not in the catalog.
    """
    catalog = load_all_primitives()
    if key not in catalog:
        raise KeyError(f"unknown primitive '{key}'; known: {sorted(catalog)}")
    return catalog[key]
