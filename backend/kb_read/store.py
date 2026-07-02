"""KB retrieval store: two-step index-then-fetch over KB1 (CadQuery API) and
the ForgeCAD context reference.

ARCHITECTURE — index-first, fetch-second (proper RAG pattern):
  list_kb_index()         → returns a compact index of what exists in both KBs.
                            The planner reads this to understand what is available
                            BEFORE deciding what to fetch (mirrors list_primitives
                            followed by lookup_primitive).
  fetch_kb_sections(keys) → planner picks specific section keys from the index,
                            fetches only those. Compact, targeted, no noise.

This avoids the blind keyword-spray anti-pattern (send keywords, get random hits).
The planner sees the menu first, orders what it actually needs.

Token budget: index ≤ 1 500 chars, each fetched section ≤ 800 chars → a typical
fetch of 3 sections costs ≤ 2 400 chars (≈ 600 tokens). Safe for the 400k budget.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_KB_DIR = Path(__file__).resolve().parent.parent.parent / "KB"
_FORGECAD_CONTEXT_PATH = _KB_DIR / "forgecad-context.md"


# ── ForgeCAD context: load and index ──────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_forgecad_sections() -> dict[str, str]:
    """Load forgecad-context.md and split into {slug: body} pairs.

    Uses ## headings as section boundaries. Cached after first load — the file
    is static at runtime. Slug = lowercase-hyphenated heading for stable keys.

    Returns:
        Ordered dict {slug: section_body}. Empty if file not found.
    """
    if not _FORGECAD_CONTEXT_PATH.exists():
        return {}
    text = _FORGECAD_CONTEXT_PATH.read_text(encoding="utf-8")
    raw_chunks = re.split(r"(?=^#{1,3} )", text, flags=re.MULTILINE)
    result: dict[str, str] = {}
    for chunk in raw_chunks:
        if not chunk.strip():
            continue
        first_line = chunk.split("\n", 1)[0].strip()
        heading_text = re.sub(r"^#+\s*", "", first_line)
        # Slug: lowercase, spaces→hyphens, drop special chars
        slug = re.sub(r"[^\w\s-]", "", heading_text.lower()).strip()
        slug = re.sub(r"[\s_]+", "-", slug)
        if slug and slug not in result:
            result[slug] = chunk
    return result


# ── KB1: CadQuery API — category index ────────────────────────────────────────

_CQ_CATEGORIES: dict[str, str] = {
    # slug → description (used in the index the planner reads)
    "3d-primitives":   "box, sphere, cylinder, wedge — direct 3D solids",
    "2d-sketch":       "rect, circle, polygon, slot2D, ellipse, polyline, spline",
    "3d-operations":   "extrude, revolve, sweep, loft, split, cutBlind, cutThruAll, twistExtrude",
    "holes":           "hole, cboreHole (counterbore), cskHole (countersink)",
    "modification":    "fillet, chamfer, shell — edge/face post-processing",
    "boolean":         "cut, union, intersect — CSG operations",
    "multi-point":     "pushPoints, rarray, polarArray — repeating features",
    "transform":       "translate, rotate, mirror — placement",
    "selection":       "faces(), edges(), vertices(), wires() + selector strings (>Z, |X, %Circle)",
}

_FORGECAD_SECTION_DESCRIPTIONS: dict[str, str] = {
    # key phrases in forgecad-context.md sections and what they cover
    "forgecad-api-reference":       "ForgeCAD globals: box, cylinder, sphere, cone, torus",
    "core-concepts":                "Param.number() sliders, return shapes, injected globals",
    "shapes-and-operations":        "union, subtract, intersect, translate, rotate, scale",
    "sketch-and-profiles":          "polygon(), rect(), circle() sketch primitives for extrude/revolve",
    "sweep":                        "sweep(profile, path) — tube, pipe, curved extrusion",
    "revolve":                      "revolve() — axisymmetric solids: bottles, cups, rings",
    "loft":                         "loft([profiles]) — blend between cross-sections",
    "assembly-and-placement":       "place(), placeReference(), align, mate constraints",
    "fillet-and-chamfer":           "fillet(r), chamfer(r) — ForgeCAD edge rounding",
    "shell":                        "shell(t) — hollow out a solid",
    "import-and-composition":       "require() for sub-models, importSvgSketch()",
    "boolean-operations":           "union(), subtract(), intersect() in ForgeCAD",
    "parameters-and-param":         "Param.number(), Param.string() — UI sliders",
}


def list_kb_index() -> dict[str, dict[str, str]]:
    """Return a compact index of the CadQuery KB (KB1).

    The planner calls this once to see the menu, then calls fetch_kb_sections()
    with the keys it actually needs. This is the index, NOT the content.

    The ForgeCAD section was removed with the forge compiler (scope reduction):
    serving it bloated the pre-injected planner context every step and pointed at a
    code path that no longer exists. _load_forgecad_sections + the forgecad
    descriptions remain on disk (unused) in case forge is ever revived.

    Returns:
        {"cadquery": {slug: description, ...}}    # KB1 categories only
    """
    return {"cadquery": _CQ_CATEGORIES}


def fetch_kb_sections(keys: list[str]) -> dict[str, str]:
    """Fetch specific KB sections by their slug keys from list_kb_index().

    Args:
        keys: List of slug keys from list_kb_index()'s "cadquery" menu, e.g.
              ["3d-operations", "holes", "modification"].

    Returns:
        {key: content_snippet} for each found key. Missing keys are silently
        omitted (the planner must handle partial results). Each snippet is
        capped at 800 chars to stay within token budget.
    """
    result: dict[str, str] = {}

    for key in keys:
        if key not in _CQ_CATEGORIES:
            continue  # forgecad keys no longer served (forge path removed)
        try:
            from KB.rag_kb1 import WORKPLANE_DOCS
        except ImportError:
            result[key] = f"[KB1 unavailable: {key}]"
            continue

        # KB1 uses underscores in category field; index uses hyphens in slugs
        category = key.replace("-", "_")
        docs = [d for d in WORKPLANE_DOCS if d.category == category]
        if docs:
            lines = [f"## CadQuery: {key}\n"]
            for doc in docs[:4]:  # cap at 4 methods per category
                lines.append(f"  {doc.signature}")
                lines.append(f"    {doc.description[:200]}")
                if doc.example:
                    lines.append(f"    Example: {doc.example}")
                lines.append("")
            snippet = "\n".join(lines)
            result[key] = snippet[:800] + ("…" if len(snippet) > 800 else "")

    return result
