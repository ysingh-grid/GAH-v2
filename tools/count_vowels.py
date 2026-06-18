def count_vowels_in_long_word(text: str) -> int:
    """Count the number of vowels (a, e, i, o, u) in a word.
    
    IMPORTANT: This tool should only be called for long words (8 or more characters) else make it to 0.
    
    Args:
        text: The word to inspect.
        
    Returns:
        The total number of vowels.
    """
    import re
    return len(re.findall(r'[aeiouAEIOU]', text))
