from pathlib import Path

from backend.config import settings
from backend.security.path_guard import ensure_read_allowed, relative_path


def scan_repo(path: str, max_depth: int, include_extensions: list[str], exclude_dirs: list[str]) -> dict:
    root = ensure_read_allowed(path)
    max_depth = max(0, min(max_depth, 12))
    include = set(include_extensions)
    exclude = set(exclude_dirs) | {".git", "__pycache__", ".venv", "node_modules", "dist", "build"}
    files: list[dict] = []
    directories: set[str] = set()

    def walk(current: Path, depth: int) -> None:
        if depth > max_depth or not current.is_dir():
            return
        for child in sorted(current.iterdir(), key=lambda item: item.name):
            if child.name in exclude or child.name.startswith("."):
                continue
            rel = relative_path(child)
            if child.is_dir():
                directories.add(rel)
                walk(child, depth + 1)
            elif child.is_file() and child.suffix in include and child.stat().st_size <= settings.max_read_bytes:
                files.append({"path": rel, "type": "file", "size_bytes": child.stat().st_size})

    walk(root, 0)
    root_rel = "." if root == settings.project_root else relative_path(root)
    return {"root": root_rel, "files": files, "directories": sorted(directories)}
