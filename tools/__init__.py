from tools.get_primitives import get_primitives_library
from tools.select_best import select_best_candidate


REGISTRY = {
    "get_primitives_library": get_primitives_library,
    "select_best_candidate": select_best_candidate,
}


def get_tools(names=None):
    """Return the callables for `names` (or all if None)."""
    if not names:
        return list(REGISTRY.values())
    return [REGISTRY[n] for n in names]