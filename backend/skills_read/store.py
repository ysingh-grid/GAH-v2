from pathlib import Path

# parents[2] = repo root (store.py -> skills_read -> backend -> ROOT), then /skills
_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


def load_all_skills() -> list[str]:
    """Names of every skill guide, e.g. ['playbook', 'intent_extraction', ...].

    SKILLS.md is the human index, not a skill — excluded.
    """
    return sorted(p.stem for p in _SKILLS_DIR.glob("*.md") if p.stem != "SKILLS")


def read_skill(name: str) -> str:
    """Raw markdown of one skill. Raises KeyError if it doesn't exist."""
    path = _SKILLS_DIR / f"{name}.md"
    if not path.is_file():
        raise KeyError(f"unknown skill '{name}'; known: {load_all_skills()}")
    return path.read_text(encoding="utf-8")