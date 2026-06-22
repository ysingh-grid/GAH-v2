from pathlib import Path

from backend.config import settings
from backend.utils.response import BridgeError


ALLOWED_READ_ROOTS = (
    "skills",
    "pipelines",
    "output",
    "outputs",
    "traces",
    "backend",
    "rlm",
    "tools",
    "fast_rlm",
    "primitives",
    "generated",
    "tests",
)
ALLOWED_WRITE_ROOTS = ("pipelines", "output", "traces", "generated")
SOURCE_WRITE_ROOTS = ("backend", "rlm", "skills", "tools", "tests")
SAFE_TEXT_EXTENSIONS = (".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".env.example")
SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}


def _looks_like_traversal(path: str) -> bool:
    return any(part == ".." for part in Path(path).parts)


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def relative_path(path: Path) -> str:
    return path.relative_to(settings.project_root).as_posix()


def resolve_project_path(path: str) -> Path:
    if not path or path.strip() == "":
        raise BridgeError("PATH_NOT_ALLOWED", "Path must not be empty")
    if _looks_like_traversal(path):
        raise BridgeError("PATH_NOT_ALLOWED", f"Path traversal is not allowed: {path}")

    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = settings.project_root / candidate
    resolved = candidate.resolve()
    if not _is_inside(resolved, settings.project_root):
        raise BridgeError("PATH_NOT_ALLOWED", f"Path is outside project root: {path}")
    return resolved


def ensure_read_allowed(path: str | Path, allow_direct_root_file: bool = True) -> Path:
    resolved = resolve_project_path(str(path))
    rel = resolved.relative_to(settings.project_root)
    parts = rel.parts

    if not parts:
        return resolved

    name = resolved.name
    if name in SENSITIVE_NAMES or name.startswith(".env"):
        raise BridgeError("PATH_NOT_ALLOWED", f"Sensitive file is not readable: {rel.as_posix()}")
    if name.startswith(".") and name != ".env.example":
        raise BridgeError("PATH_NOT_ALLOWED", f"Hidden files are not readable: {rel.as_posix()}")
    if any(part in {".git", ".venv", "__pycache__", "node_modules"} for part in parts):
        raise BridgeError("PATH_NOT_ALLOWED", f"Path is in a blocked directory: {rel.as_posix()}")

    if len(parts) == 1 and allow_direct_root_file:
        return resolved
    if parts[0] not in ALLOWED_READ_ROOTS:
        raise BridgeError("PATH_NOT_ALLOWED", f"Read root is not allowed: {parts[0]}")
    return resolved


def ensure_write_allowed(path: str | Path) -> Path:
    resolved = resolve_project_path(str(path))
    rel = resolved.relative_to(settings.project_root)
    parts = rel.parts
    if not parts:
        raise BridgeError("PATH_NOT_ALLOWED", "Cannot write project root")

    first = parts[0]
    if first in SOURCE_WRITE_ROOTS and not settings.allow_source_write:
        raise BridgeError("PATH_NOT_ALLOWED", f"Source writes are disabled for: {first}")
    if first not in ALLOWED_WRITE_ROOTS and not (settings.allow_source_write and first in SOURCE_WRITE_ROOTS):
        raise BridgeError("PATH_NOT_ALLOWED", f"Write root is not allowed: {first}")
    if any(part in {".git", ".venv", "__pycache__", "node_modules"} for part in parts):
        raise BridgeError("PATH_NOT_ALLOWED", f"Writes are blocked for: {rel.as_posix()}")
    if resolved.name in SENSITIVE_NAMES or resolved.name.startswith(".env"):
        raise BridgeError("PATH_NOT_ALLOWED", f"Sensitive file writes are blocked: {rel.as_posix()}")
    return resolved
