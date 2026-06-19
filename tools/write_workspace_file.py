from pathlib import Path


WORKSPACE_ROOT = Path(__file__).parent.parent.resolve()


def resolve_workspace_path(filename: str) -> Path:
    """Resolve a path and require it to stay inside the workspace."""
    path = Path(filename)
    if not path.is_absolute():
        path = WORKSPACE_ROOT / path
    resolved = path.resolve()
    if resolved != WORKSPACE_ROOT and WORKSPACE_ROOT not in resolved.parents:
        raise ValueError(f"Path escapes workspace: {filename}")
    return resolved


def workspace_relative(path: Path) -> str:
    return path.resolve().relative_to(WORKSPACE_ROOT).as_posix()


def write_workspace_file(filename: str, content: str) -> str:
    """Write a file to the host workspace filesystem.
    
    Args:
        filename: The relative or absolute path of the file to write.
        content: The text content to write into the file.
        
    Returns:
        A success message or status.
    """
    path = resolve_workspace_path(filename)
    
    # Ensure parent directories exist
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Successfully wrote {len(content)} characters to {workspace_relative(path)}."
