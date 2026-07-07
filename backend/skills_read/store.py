import re
from pathlib import Path

# parents[2] = repo root (store.py -> skills_read -> backend -> ROOT), then /skills
_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

# Index files (curated, role-scoped catalogs). These — not a raw directory glob —
# are what the two list tools return, so the planner and replanner each discover
# ONLY their own guides. read_skill still serves any file by name (access is open;
# discovery is scoped), so a shared guide named in both indexes resolves fine.
_PLANNER_INDEX = "SKILLS.md"
_REPLAN_INDEX = "SKILLS_replan.md"

# Names that are index files, not skills (excluded from the dir-glob fallback).
_NON_SKILL_STEMS = {"SKILLS", "SKILLS_replan"}


def _parse_index(filename: str) -> list[str]:
    """Return the skill names listed in an index file, in file order.

    An index is a markdown bullet list; each bullet's FIRST backtick-quoted
    token is the skill name (e.g. ``- `playbook`  ← read first``). File order
    is preserved so 'read first' guides stay first.
    """
    path = _SKILLS_DIR / filename
    names: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        m = re.search(r"`([^`]+)`", stripped)
        if m:
            names.append(m.group(1))
    return names


def load_planner_skills() -> list[str]:
    """The planner's guide catalog — the names in SKILLS.md only."""
    return _parse_index(_PLANNER_INDEX)


def load_replan_skills() -> list[str]:
    """The replanner's guide catalog — the names in SKILLS_replan.md only."""
    return _parse_index(_REPLAN_INDEX)


def load_all_skills() -> list[str]:
    """Every skill file on disk (used only for read_skill's error hint).

    Not exposed to agents directly — the role-scoped index loaders above are.
    """
    return sorted(p.stem for p in _SKILLS_DIR.glob("*.md") if p.stem not in _NON_SKILL_STEMS)


def read_skill(name: str) -> str:
    """Raw markdown of one skill. Raises KeyError if it doesn't exist."""
    path = _SKILLS_DIR / f"{name}.md"
    if not path.is_file():
        raise KeyError(f"unknown skill '{name}'; known: {load_all_skills()}")
    return path.read_text(encoding="utf-8")
