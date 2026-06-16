def lookup_primitive(name: str) -> dict:
    """
    Looks up the schema and details of a primitive in the primitives library.
    
    Args:
        name: Name of the primitive (e.g., 'cone', 'box').
        
    Returns:
        A dictionary containing description, parameters, verification, and template.
    """
    import os
    import json
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    library_path = os.path.join(base_dir, "primitives", "library.json")
    
    if not os.path.exists(library_path):
        raise FileNotFoundError(f"Primitives library file not found at {library_path}")
        
    with open(library_path, "r", encoding="utf-8") as f:
        library = json.load(f)
        
    if name not in library:
        raise ValueError(f"Primitive '{name}' is not supported. Supported list: {list(library.keys())}")
        
    return library[name]


def list_primitives() -> list[str]:
    """
    Lists the names of all primitives supported in the primitives library.
    
    Returns:
        A list of primitive names.
    """
    import os
    import json
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    library_path = os.path.join(base_dir, "primitives", "library.json")
    
    if not os.path.exists(library_path):
        return []
        
    with open(library_path, "r", encoding="utf-8") as f:
        library = json.load(f)
        
    return sorted(list(library.keys()))
