from .calculate_string_length import calculate_string_length
from .count_vowels import count_vowels_in_long_word

REGISTRY = {
    "string_length": calculate_string_length,
    "count_vowels": count_vowels_in_long_word,
}


def get_tools(names=None):
    """Return the callables for `names` (or all if None)."""
    if not names:
        return list(REGISTRY.values())
    return [REGISTRY[n] for n in names]