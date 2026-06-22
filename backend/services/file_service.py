import os

from backend.config import settings
from backend.security.path_guard import (
    SAFE_TEXT_EXTENSIONS,
    ensure_read_allowed,
    ensure_write_allowed,
    relative_path,
)
from backend.utils.response import BridgeError


def _has_safe_extension(path: str) -> bool:
    return path.endswith(SAFE_TEXT_EXTENSIONS)


def read_file(path: str) -> dict:
    resolved = ensure_read_allowed(path)
    if not resolved.exists() or not resolved.is_file():
        raise BridgeError("FILE_NOT_FOUND", f"File not found: {path}")
    rel = relative_path(resolved)
    if not _has_safe_extension(rel):
        raise BridgeError("FILE_TYPE_NOT_ALLOWED", f"File type is not readable: {rel}")
    size = resolved.stat().st_size
    if size > settings.max_read_bytes:
        raise BridgeError("FILE_TOO_LARGE", f"File exceeds {settings.max_read_bytes} bytes: {rel}")
    return {"path": rel, "content": resolved.read_text(encoding="utf-8"), "size_bytes": size}


def write_file(path: str, content: str, overwrite: bool) -> dict:
    resolved = ensure_write_allowed(path)
    rel = relative_path(resolved)
    if not _has_safe_extension(rel):
        raise BridgeError("FILE_TYPE_NOT_ALLOWED", f"File type is not writable: {rel}")
    exists = resolved.exists()
    if exists and not overwrite:
        raise BridgeError("INVALID_REQUEST", f"File already exists: {rel}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    encoded = content.encode("utf-8")
    resolved.write_text(content, encoding="utf-8")
    return {"path": rel, "bytes_written": len(encoded), "created": not exists}


def list_dir(path: str) -> dict:
    resolved = ensure_read_allowed(path)
    if not resolved.exists():
        raise BridgeError("FILE_NOT_FOUND", f"Directory not found: {path}")
    if not resolved.is_dir():
        raise BridgeError("INVALID_REQUEST", f"Path is not a directory: {path}")
    items = []
    for child in sorted(resolved.iterdir(), key=lambda item: item.name):
        if child.name.startswith(".") or child.name in {".git", "__pycache__", ".venv", "node_modules"}:
            continue
        items.append({"name": child.name, "path": relative_path(child), "type": "directory" if child.is_dir() else "file"})
    return {"path": os.fspath(relative_path(resolved)), "items": items}
