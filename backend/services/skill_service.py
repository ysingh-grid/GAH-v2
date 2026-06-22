import re

from backend.config import settings
from backend.security.path_guard import relative_path
from backend.utils.response import BridgeError

SKILL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def list_skills() -> dict:
    if not settings.skills_dir.exists():
        return {"skills": []}
    skills = [
        {"name": path.stem, "path": relative_path(path)}
        for path in sorted(settings.skills_dir.glob("*.md"))
        if path.is_file()
    ]
    return {"skills": skills}


def read_skill(skill_name: str) -> dict:
    if not SKILL_RE.fullmatch(skill_name):
        raise BridgeError("INVALID_REQUEST", "Skill name may only contain letters, numbers, dash, and underscore")

    path = settings.skills_dir / f"{skill_name}.md"
    if not path.exists() or not path.is_file():
        raise BridgeError("SKILL_NOT_FOUND", f"Skill not found: {skill_name}")
    return {"skill_name": skill_name, "path": relative_path(path), "content": path.read_text(encoding="utf-8")}
