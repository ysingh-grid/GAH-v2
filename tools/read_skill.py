def read_skill(name: str) -> str:
    """
    Reads the content of a skill markdown file from the skills/ directory.
    
    Args:
        name: Name of the skill (e.g., 'intent_extraction') without directory path or extension.
        
    Returns:
        The text content of the skill file.
    """
    import os
    
    # Dynamic path resolution to find skills sibling directory
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skills_dir = os.path.join(base_dir, "skills")
    
    # Sanitize name to prevent path traversal
    name = os.path.basename(name)
    if not name.endswith(".md"):
        name = name + ".md"
        
    file_path = os.path.join(skills_dir, name)
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Skill file not found at {file_path}")
        
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def list_skills() -> list[str]:
    """
    Lists the names of all skills available in the skills/ directory.
    
    Returns:
        A list of skill names without the '.md' extension.
    """
    import os
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skills_dir = os.path.join(base_dir, "skills")
    
    if not os.path.exists(skills_dir):
        return []
        
    skills = []
    for f in os.listdir(skills_dir):
        if f.endswith(".md"):
            skills.append(f[:-3])
            
    return sorted(skills)
