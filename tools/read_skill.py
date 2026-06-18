"""
tools/read_skill.py

Skill reader with Claude Skills Style metadata support.

All skills live in skills/*.md with a YAML frontmatter block at the top.
Frontmatter is delimited by --- lines and is parsed as key: value pairs.

Functions
---------
read_skill(name)       → str   Full body of the skill (for LLM prompt injection)
read_skill_meta(name)  → dict  Metadata only — instant, zero LLM tokens
read_skill_body(name)  → str   Body only, without the frontmatter section
list_skills(tag=None)  → list  Names of all skills (optionally filtered by tag)
"""

from __future__ import annotations

import os
import re
from typing import Optional

_SKILLS_DIR: Optional[str] = None


def _get_skills_dir() -> str:
    global _SKILLS_DIR
    if _SKILLS_DIR is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _SKILLS_DIR = os.path.join(base_dir, "skills")
    return _SKILLS_DIR


def _skill_path(name: str) -> str:
    """Resolve the absolute path for a skill name."""
    skills_dir = _get_skills_dir()
    name = os.path.basename(name)  # prevent path traversal
    if not name.endswith(".md"):
        name = name + ".md"
    path = os.path.join(skills_dir, name)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Skill '{name}' not found in {skills_dir}.\n"
            f"Available: {', '.join(list_skills())}"
        )
    return path


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """
    Split a skill file into (metadata_dict, body_text).

    Frontmatter is the YAML block between the first two '---' lines.
    If no frontmatter is present, returns ({}, full_text).
    """
    if not text.startswith("---"):
        return {}, text

    # Find closing ---
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    fm_block = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")

    meta: dict = {}
    # Simple YAML-subset parser: handles scalar, list, and multiline string values
    lines = fm_block.split("\n")
    i = 0
    current_key: Optional[str] = None
    current_list: Optional[list] = None
    current_multiline: Optional[list] = None

    def _flush():
        nonlocal current_key, current_list, current_multiline
        if current_key is None:
            return
        if current_list is not None:
            meta[current_key] = current_list
        elif current_multiline is not None:
            meta[current_key] = " ".join(current_multiline)
        current_key = None
        current_list = None
        current_multiline = None

    while i < len(lines):
        line = lines[i]

        # Top-level key: value
        kv = re.match(r'^(\w[\w_-]*):\s*(.*)', line)
        if kv:
            _flush()
            key, val = kv.group(1), kv.group(2).strip()
            # Strip inline YAML comments (e.g. "low   # ~300 tokens" → "low")
            val = re.sub(r'\s+#.*$', '', val).strip()
            current_key = key

            if val == "" or val == "|" or val == ">":
                # Next lines are list items or multiline string
                if val == "":
                    current_list = []
                else:
                    current_multiline = []
            else:
                meta[key] = val
                current_key = None

        # List item under a key
        elif line.strip().startswith("- ") and current_key and current_list is not None:
            current_list.append(line.strip()[2:].strip())

        # Multiline continuation
        elif line.startswith("  ") and current_key and current_multiline is not None:
            stripped = line.strip()
            if stripped:
                current_multiline.append(stripped)

        i += 1

    _flush()

    # Parse tags list if stored as a YAML inline list "[a, b, c]"
    if "tags" in meta and isinstance(meta["tags"], str):
        raw = meta["tags"].strip("[]")
        meta["tags"] = [t.strip() for t in raw.split(",") if t.strip()]

    return meta, body


# ── Public API ────────────────────────────────────────────────────────────────

def read_skill(name: str) -> str:
    """
    Read the FULL content of a skill file (frontmatter + body).
    Use this when injecting a skill into an LLM prompt.

    Args:
        name: Skill name without extension (e.g., 'cadquery_cookbook')

    Returns:
        Full text of the skill file as a string.
    """
    path = _skill_path(name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def read_skill_body(name: str) -> str:
    """
    Read ONLY the body of a skill (everything after the frontmatter).
    Saves a few tokens by omitting metadata from the LLM prompt.

    Args:
        name: Skill name without extension

    Returns:
        Body text of the skill (no YAML frontmatter).
    """
    path = _skill_path(name)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    _, body = _parse_frontmatter(text)
    return body


def read_skill_meta(name: str) -> dict:
    """
    Read ONLY the metadata of a skill — instant, no LLM tokens consumed.
    Use this to select which skills to load based on phase / tag / token_budget.

    Args:
        name: Skill name without extension

    Returns:
        Dict of metadata fields from the YAML frontmatter.
        Returns {} if no frontmatter is present.

    Example:
        meta = read_skill_meta("cadquery_cookbook")
        # → {"name": "cadquery_cookbook", "token_budget": "medium",
        #    "tags": ["codegen", "cadquery", ...], "used_by": [...], ...}
    """
    path = _skill_path(name)
    # Read only the first 50 lines — frontmatter is always at the top
    lines: list[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            lines.append(line)
            if i > 0 and line.strip() == "---":
                break  # stop at closing delimiter
            if i > 60:
                break  # safety — malformed frontmatter

    meta, _ = _parse_frontmatter("".join(lines))
    return meta


def list_skills(tag: Optional[str] = None) -> list[str]:
    """
    List all available skill names (without .md extension).

    Args:
        tag: Optional tag string to filter by (e.g., 'W01', 'repair', 'phase1').
             If None, returns all skills.

    Returns:
        Sorted list of skill names.

    Example:
        list_skills()           # → all skills
        list_skills("W01")      # → skills tagged for W·01 planning phase
        list_skills("repair")   # → ["repair_guidance"]
    """
    skills_dir = _get_skills_dir()
    if not os.path.exists(skills_dir):
        return []

    names = sorted(
        f[:-3]
        for f in os.listdir(skills_dir)
        if f.endswith(".md")
    )

    if tag is None:
        return names

    # Filter by tag — read metadata for each (fast: only reads header lines)
    result = []
    for name in names:
        try:
            meta = read_skill_meta(name)
            skill_tags = meta.get("tags", [])
            if isinstance(skill_tags, list) and tag in skill_tags:
                result.append(name)
            elif isinstance(skill_tags, str) and tag in skill_tags:
                result.append(name)
        except Exception:
            continue

    return result
