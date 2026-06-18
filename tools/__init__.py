REGISTRY = {}


def get_tools(names=None):
    """Return the callables for `names` (or all if None)."""
    if not names:
        return list(REGISTRY.values())
    return [REGISTRY[n] for n in names]