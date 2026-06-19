import re
import ssl
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


WORKSPACE_ROOT = Path(__file__).parent.parent.resolve()
FORGECAD_DOCS_PATH = WORKSPACE_ROOT / "skills" / "forgecad.md"


TOPICS: dict[str, dict[str, Any]] = {
    "concepts": {
        "url": "https://forgecad.io/docs/concepts",
        "docs": ["docs/API/core/concepts.md"],
        "keywords": ["concept", "runtime", "return", "script", "global", "inject", "metadata"],
        "symbols": ["param", "return", "require", "placeReference"],
        "summary": "Execution model, injected globals, imports, valid returns.",
    },
    "core": {
        "url": "https://forgecad.io/docs/core",
        "docs": ["docs/generated/core.md", "docs/guides/positioning.md"],
        "keywords": [
            "box", "cube", "cylinder", "sphere", "primitive", "boolean", "subtract",
            "union", "intersect", "translate", "rotate", "param", "chamfer", "fillet",
            "edge", "center", "hole", "shell",
        ],
        "symbols": [
            "param", "box", "cylinder", "sphere", "translate", "rotate",
            "placeReference", "subtract", "add", "intersect", "chamferTrackedEdge",
            "filletTrackedEdge",
        ],
        "summary": "Primitives, transforms, booleans, parameters, placement, edge operations.",
    },
    "sketch": {
        "url": "https://forgecad.io/docs/sketch",
        "docs": ["docs/generated/sketch.md"],
        "keywords": [
            "sketch", "profile", "extrude", "rect", "circle", "polygon", "ngon",
            "slot", "path", "text", "2d", "offset",
        ],
        "symbols": [
            "rect", "circle2d", "roundedRect", "polygon", "ngon", "slot",
            "union2d", "difference2d", "extrude", "filletCorners",
        ],
        "summary": "2D profiles, sketch booleans, paths, text, extrusion.",
    },
    "curves": {
        "url": "https://forgecad.io/docs/curves",
        "docs": ["docs/generated/curves.md"],
        "keywords": ["curve", "spline", "loft", "sweep", "surface", "strap", "smooth"],
        "symbols": ["loft", "loftAlongSpine", "sweep", "spline3d", "variableSweep"],
        "summary": "Loft, sweep, splines, curves, and surfacing.",
    },
    "assembly": {
        "url": "https://forgecad.io/docs/assembly",
        "docs": ["docs/generated/assembly.md", "docs/guides/positioning.md", "docs/guides/joint-design.md"],
        "keywords": [
            "assembly", "joint", "hinge", "slider", "mate", "connector",
            "connect", "multi-part", "multipart", "mechanism", "moving",
        ],
        "symbols": ["assembly", "joint", "addPart", "addJoint", "addRevolute", "connect", "match", "withConnectors"],
        "summary": "Multi-part assemblies, joints, connectors, mating, mechanisms.",
    },
    "output": {
        "url": "https://forgecad.io/docs/output",
        "docs": ["docs/generated/output.md"],
        "keywords": ["output", "export", "stl", "step", "bom", "dimension", "metadata"],
        "symbols": ["bom", "bomToCsv", "dimension", "export"],
        "summary": "Exports, BOM, dimensions, and output metadata.",
    },
    "lib": {
        "url": "https://forgecad.io/docs/lib",
        "docs": ["docs/generated/lib.md"],
        "keywords": ["lib", "library", "modeled-screw", "bolt", "nut", "washer", "gear", "bearing", "fastener", "hardware"],
        "symbols": ["bolt", "nut", "washer", "gear", "bearing"],
        "summary": "Fasteners, gears, bearings, and reusable hardware.",
    },
    "sheet-metal": {
        "url": "https://forgecad.io/docs/sheet-metal",
        "docs": ["docs/generated/sheet-metal.md"],
        "keywords": ["sheet metal", "sheet-metal", "bend", "flange", "flat pattern", "k-factor", "panel"],
        "symbols": ["sheetMetal", "flange", "cutout", "folded", "flatPattern"],
        "summary": "Bends, flanges, panels, flat patterns, K-factor.",
    },
    "viewport": {
        "url": "https://forgecad.io/docs/viewport",
        "docs": ["docs/generated/viewport.md"],
        "keywords": ["viewport", "render", "view", "label", "cutaway", "cut plane", "inspect", "camera"],
        "symbols": ["scene", "Viewport", "cutPlane", "explodeView", "jointsView", "label"],
        "summary": "Viewer-only views, cut planes, labels, render settings.",
    },
    "sdf": {
        "url": "https://forgecad.io/docs/sdf",
        "docs": ["docs/generated/sdf.md"],
        "keywords": ["sdf", "organic", "blob", "implicit", "smooth", "lattice", "tpms", "gyroid"],
        "symbols": ["sdf", "smoothUnion", "toShape", "fromFunction", "gyroid"],
        "summary": "Organic, smooth implicit geometry, lattices, TPMS.",
    },
}


ALIASES = {
    "curves-and-surfaces": "curves",
    "curve": "curves",
    "sketches": "sketch",
    "library": "lib",
    "sheet": "sheet-metal",
    "sheetmetal": "sheet-metal",
    "sheet_metal": "sheet-metal",
    "view": "viewport",
    "views": "viewport",
}


FORBIDDEN_PATTERNS = [
    (r"\bCadQuery\b|\bcadquery\b|import\s+cadquery", "CadQuery/Python CAD is forbidden"),
    (r"\bcq\.", "CadQuery cq. API is forbidden"),
    (r"\bWorkplane\b", "CadQuery Workplane API is forbidden"),
    (r"\bCSG\b", "CSG/OpenJSCAD API is forbidden"),
    (r"@jscad/modeling|modeling\.primitives", "JSCAD modeling API is forbidden"),
    (r"\bmodule\.exports\b|\bexports\.", "ForgeCAD scripts should return top-level geometry, not module exports"),
    (r"\bfunction\s+main\b|\bconst\s+main\b|\blet\s+main\b", "Do not wrap generated ForgeCAD in main()"),
    (r"\.translate\s*\(\s*\[", "NEVER pass an array to .translate([x, y, z]). Use positional arguments: .translate(x, y, z)"),
    (r"\.rotate\s*\(\s*\[", "NEVER pass an array to .rotate([degX, degY, degZ]). Use positional arguments: .rotate(degX, degY, degZ)"),
    (r"\.subtract\s*\(\s*\)|\.union\s*\(\s*\)", "Boolean operations cannot be empty. Pass shape operands as arguments"),
]


SHADOWED_GLOBALS = [
    "box", "cylinder", "sphere", "group", "assembly", "param", "chamfer",
    "fillet", "union", "difference", "cube", "rect", "circle2d", "polygon",
    "ngon", "loft", "sweep",
]


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip = True
        if tag in {"h1", "h2", "h3", "h4", "p", "li", "pre", "code"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip = False
        if tag in {"h1", "h2", "h3", "h4", "p", "li", "pre"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self.parts.append(text + " ")

    def text(self) -> str:
        raw = "".join(self.parts)
        return re.sub(r"\n{3,}", "\n\n", raw)


def _normalize_topic(topic: str) -> str:
    key = topic.strip().lower().replace(" ", "-")
    return ALIASES.get(key, key)


def _read_local_docs() -> str:
    if not FORGECAD_DOCS_PATH.exists():
        raise FileNotFoundError(f"ForgeCAD docs snapshot not found: {FORGECAD_DOCS_PATH}")
    return FORGECAD_DOCS_PATH.read_text(encoding="utf-8")


def _extract_doc_section(source: str, doc_name: str) -> str:
    marker = f"## File: `{doc_name}`"
    start = source.find(marker)
    if start < 0:
        return ""
    next_start = source.find("\n## File: `", start + len(marker))
    return source[start:].strip() if next_start < 0 else source[start:next_start].strip()


def _window_for_term(text: str, term: str, radius: int = 850) -> str:
    # 1. Prioritize precise heading block matching for the symbol (e.g. ### `symbol` or #### symbol(...))
    heading_pattern = rf"(?:^|\n)(#+\s+[^#\n]*\b{re.escape(term)}\b[^#\n]*\n.*?)(?=(?:\n#+\s)|\Z)"
    match = re.search(heading_pattern, text, re.IGNORECASE | re.DOTALL)
    if match:
        snippet = match.group(1).strip()
        return snippet[:1500]

    # 2. Fallback to looser heading matching
    match_fallback = re.search(rf"(?:^|\n)(#+\s+.*`?{re.escape(term)}`?.*.*?)(?=(?:\n#+\s)|\Z)", text, re.IGNORECASE | re.DOTALL)
    if match_fallback:
        snippet = match_fallback.group(1).strip()
        return snippet[:1500]

    index = text.lower().find(term.lower())
    if index < 0:
        return ""
    start = max(0, index - radius)
    end = min(len(text), index + radius)
    return text[start:end].strip()


def _compact(text: str, max_chars: int = 5500) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    text = re.sub(r"[ \t]{2,}", " ", text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 120].rstrip() + "\n...[truncated: use a narrower topic for more detail]"


def forgecad_doc_topics(prompt: str) -> list[str]:
    """Select ForgeCAD doc topics relevant to a natural-language CAD prompt."""
    prompt_lower = prompt.lower()
    scores: dict[str, int] = {"concepts": 1, "core": 1}

    for topic, data in TOPICS.items():
        score = sum(1 for keyword in data["keywords"] if keyword in prompt_lower)
        if score:
            scores[topic] = scores.get(topic, 0) + score

    ordered = sorted(scores, key=lambda t: (-scores[t], list(TOPICS).index(t)))
    return ordered[:5]


def forgecad_api_lookup(topic: str) -> dict[str, Any]:
    """Return compact local ForgeCAD API snippets for a topic or symbol."""
    raw_topic = topic.strip()
    normalized = _normalize_topic(raw_topic)
    source = _read_local_docs()

    if normalized in TOPICS:
        data = TOPICS[normalized]
        sections = "\n\n".join(_extract_doc_section(source, doc) for doc in data["docs"])
        snippets = []
        for symbol in data["symbols"]:
            snippet = _window_for_term(sections, symbol)
            if snippet and snippet not in snippets:
                snippets.append(snippet)
        if not snippets:
            snippets = [sections[:4500]]
        return {
            "topic": normalized,
            "summary": data["summary"],
            "url": data["url"],
            "source": "local skills/forgecad.md",
            "snippets": _compact("\n\n---\n\n".join(snippets)),
            "warnings": [],
        }

    snippets = []
    for section_name in [data["docs"][0] for data in TOPICS.values()]:
        section = _extract_doc_section(source, section_name)
        snippet = _window_for_term(section, raw_topic)
        if snippet and snippet not in snippets:
            snippets.append(snippet)
    if not snippets:
        return {
            "topic": raw_topic,
            "summary": "No local match found",
            "url": None,
            "source": "local skills/forgecad.md",
            "snippets": "",
            "warnings": ["No local ForgeCAD doc match. Use forgecad_web_doc_lookup only if this API is required."],
        }
    return {
        "topic": raw_topic,
        "summary": "Symbol search across local ForgeCAD docs",
        "url": None,
        "source": "local skills/forgecad.md",
        "snippets": _compact("\n\n---\n\n".join(snippets)),
        "warnings": [],
    }


def forgecad_web_doc_lookup(topic: str) -> dict[str, Any]:
    """Fetch a compact official ForgeCAD docs page as fallback."""
    normalized = _normalize_topic(topic)
    url = TOPICS.get(normalized, {}).get("url")
    if not url:
        candidate = topic.strip()
        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"}:
            url = candidate
        else:
            url = f"https://forgecad.io/docs/{normalized}"

    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "forgecad.io" or not parsed.path.startswith("/docs"):
        return {
            "topic": topic,
            "url": url,
            "source": "web",
            "snippets": "",
            "warnings": ["Rejected non-official ForgeCAD docs URL."],
        }

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "v3-capstone-forgecad-doc-lookup/1.0"})
        context = ssl.create_default_context()
        try:
            import certifi
            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
        with urllib.request.urlopen(req, timeout=8, context=context) as res:
            html = res.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "topic": normalized,
            "url": url,
            "source": "web",
            "snippets": "",
            "warnings": [f"Web lookup failed: {exc}"],
        }

    parser = _TextExtractor()
    parser.feed(html)
    snippets = _compact(parser.text(), max_chars=4500)
    warnings = []
    if len(snippets) < 200:
        warnings.append("Official docs page returned little static text; use local forgecad_api_lookup as primary source.")
    return {
        "topic": normalized,
        "url": url,
        "source": "official ForgeCAD docs",
        "snippets": snippets,
        "warnings": warnings,
    }


def forgecad_decompose_prompt(prompt: str) -> dict[str, Any]:
    """Create a deterministic scaffold the RLM can revise before coding."""
    topics = forgecad_doc_topics(prompt)
    prompt_lower = prompt.lower()
    components = []
    operations = []

    primitive_keywords = {
        "box/block/plate": ["box", "block", "plate", "rectangular"],
        "cylinder/hole/post": ["cylinder", "hole", "post", "tube", "pipe"],
        "sphere/rounded": ["sphere", "ball", "rounded"],
        "sketch/extrusion": ["sketch", "profile", "extrude", "polygon", "triangle", "slot"],
        "loft/sweep": ["loft", "sweep", "curve", "surface"],
        "assembly/joint": ["assembly", "joint", "hinge", "slider", "multi-part", "multipart"],
    }
    for name, keywords in primitive_keywords.items():
        if any(keyword in prompt_lower for keyword in keywords):
            components.append(name)

    operation_keywords = {
        "boolean subtract/cut": ["hole", "cut", "slot", "hollow", "pocket", "subtract"],
        "boolean add/union": ["add", "join", "combine", "boss", "rib"],
        "edge treatment": ["chamfer", "fillet", "round", "bevel"],
        "pattern/repetition": ["array", "pattern", "repeat", "grid", "four", "multiple"],
        "parametric dimensions": ["parametric", "parameter", "adjustable"],
    }
    for name, keywords in operation_keywords.items():
        if any(keyword in prompt_lower for keyword in keywords):
            operations.append(name)

    return {
        "prompt": prompt,
        "doc_topics": topics,
        "is_parametric": any(word in prompt_lower for word in ["parametric", "parameter", "adjustable"]),
        "likely_components": components or ["core primitive solids"],
        "likely_operations": operations or ["direct primitive construction"],
        "generation_notes": [
            "Use direct ForgeCAD JavaScript only.",
            "Call forgecad_api_lookup for each selected topic before writing code.",
            "Use placeReference('center', [0, 0, 0]) when full XYZ centering is required.",
            "Run forgecad_code_lint before write_and_export_forgecad_model.",
        ],
    }


def forgecad_code_lint(js_content: str) -> dict[str, Any]:
    """Check generated ForgeCAD JavaScript for common wrong-API patterns."""
    issues: list[dict[str, str]] = []
    code = js_content or ""

    for pattern, message in FORBIDDEN_PATTERNS:
        if re.search(pattern, code, re.IGNORECASE):
            issues.append({"severity": "error", "message": message, "pattern": pattern})

    for name in SHADOWED_GLOBALS:
        if re.search(rf"\b(const|let|var|function|class)\s+{re.escape(name)}\b", code):
            issues.append({
                "severity": "error",
                "message": f"Local declaration shadows injected ForgeCAD global: {name}",
                "pattern": name,
            })

    # Warning for reversed cylinder arguments: cylinder(radius, height)
    cyl_matches = re.findall(r"\bcylinder\s*\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\)", code)
    for r_str, h_str in cyl_matches:
        r_val = float(r_str)
        h_val = float(h_str)
        if r_val > h_val * 3 and r_val > 5:
            issues.append({
                "severity": "warning",
                "message": f"Possible reversed cylinder arguments: cylinder(radius, height). You passed radius={r_val}, height={h_val}. First parameter MUST be radius, second is height.",
                "pattern": f"cylinder({r_str}, {h_str})",
            })

    if not re.search(r"(^|\n)\s*return\s+[^;]+;?\s*(//.*)?\s*$", code.strip()):
        issues.append({
            "severity": "error",
            "message": "ForgeCAD script should end with a top-level return statement.",
            "pattern": "return",
        })

    if "try" in code and "catch" in code:
        issues.append({
            "severity": "warning",
            "message": "Avoid silent try/catch fallbacks in generated ForgeCAD.",
            "pattern": "try/catch",
        })

    return {
        "ok": not any(issue["severity"] == "error" for issue in issues),
        "issues": issues,
    }
