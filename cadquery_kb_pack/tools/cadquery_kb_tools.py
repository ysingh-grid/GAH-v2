"""
cadquery_kb_tools.py — retrieval tools over the CadQuery knowledge base.

Design for an RLM: TWO LEVELS so context stays small.
  - search / browse  -> compact hits (id + signature + one-line summary)
  - doc / example     -> the full detail for ONE id the agent chose

Deterministic keyword search (no embeddings, no network) — reproducible and
runs anywhere. The KB file lives on the host; these tools run host-side, so
register them on your host MCP server (host_mcp.py) and the RLM calls them with
  await mcp_call("cadkb", "cadquery_search", query="hole in a plate")

Use standalone (no MCP) for testing:  from cadquery_kb_tools import KB
"""

import json
import os
import re

_KB_PATH = os.environ.get(
    "CADQUERY_KB",
    os.path.join(os.path.dirname(__file__), "..", "knowledge", "cadquery_kb.json"))


def _tokens(s: str):
    return [t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) > 1]


class KB:
    """Loaded knowledge base + deterministic search. Pure Python."""

    def __init__(self, path: str = _KB_PATH):
        data = json.load(open(path, encoding="utf-8"))
        self.api = data["api"]
        self.examples = data["examples"]
        self.categories = data["categories"]
        self._by_id = {e["id"]: e for e in self.api}
        self._by_name = {}
        for e in self.api:
            self._by_name.setdefault(e["name"].lower(), e)

    # ---- compact projections (what search returns) ----
    @staticmethod
    def _hit(e):
        return {"id": e["id"], "kind": e["kind"], "signature": e["signature"],
                "summary": e["summary"][:160], "category": e["category"]}

    def _score_api(self, qtok, e):
        name = e["name"].lower()
        kw = set(e.get("keywords", []))
        s = 0
        for t in qtok:
            if t == name:
                s += 10
            elif t in name:
                s += 5
            if t in kw:
                s += 3
            if t in e["summary"].lower():
                s += 1
            if t in e["category"].lower():
                s += 1
        return s

    def search(self, query: str, k: int = 8, kind: str = "all"):
        """Find API ops and/or examples relevant to `query`. kind: api|examples|all."""
        qtok = _tokens(query)
        out = {}
        if kind in ("api", "all"):
            scored = sorted(((self._score_api(qtok, e), e) for e in self.api),
                            key=lambda x: -x[0])
            out["api"] = [self._hit(e) for sc, e in scored[:k] if sc > 0]
        if kind in ("examples", "all"):
            ex_scored = []
            for x in self.examples:
                blob = (x["title"] + " " + x["description"] + " " + " ".join(x["api_used"])).lower()
                sc = sum(blob.count(t) for t in qtok)
                ex_scored.append((sc, x))
            ex_scored.sort(key=lambda z: -z[0])
            out["examples"] = [{"id": x["id"], "title": x["title"],
                                "api_used": x["api_used"]} for sc, x in ex_scored[:max(3, k // 2)] if sc > 0]
        return out

    def doc(self, id_or_name: str):
        """Full detail for ONE API operation (signature, params, full docstring)."""
        e = self._by_id.get(id_or_name) or self._by_name.get(id_or_name.lower())
        if not e:
            raise ValueError(f"no API entry for {id_or_name!r} (try cadquery_search first)")
        return e

    def example(self, id_or_query: str):
        """Full worked example (title, description, runnable code, api_used)."""
        for x in self.examples:
            if x["id"] == id_or_query:
                return x
        hits = self.search(id_or_query, k=1, kind="examples")["examples"]
        if hits:
            return next(x for x in self.examples if x["id"] == hits[0]["id"])
        raise ValueError(f"no example for {id_or_query!r}")

    def browse(self):
        """Category -> count, so the agent can see what exists before searching."""
        return {c: len(ids) for c, ids in self.categories.items()}


# --- Always-present "verified CadQuery idioms" skill (Task 4) ----------------
# Distil the KB into a COMPACT, always-in-context cheat-sheet that GROUNDS the model on the REAL
# API (exact signatures from the KB) + the selector grammar + an explicit "these do NOT exist"
# list (verified against the live CadQuery API). The failing run hallucinated `Workplane.taper`
# and a wrong `spline` signature precisely because the KB was pull-only and never consulted; this
# PUSHES the truth into the prompt for EVERY object, not just chairs.
_IDIOM_GROUPS = [
    ("3D build", ["Workplane.box", "Workplane.cylinder", "Workplane.sphere", "Workplane.extrude",
                  "Workplane.revolve", "Workplane.loft", "Workplane.sweep"]),
    ("Holes", ["Workplane.hole", "Workplane.cboreHole", "Workplane.cskHole",
               "Workplane.cutThruAll", "Workplane.cutBlind"]),
    ("2D / profile (then extrude/revolve/loft/sweep)",
     ["Workplane.workplane", "Workplane.moveTo", "Workplane.lineTo", "Workplane.polyline",
      "Workplane.spline", "Workplane.circle", "Workplane.rect", "Workplane.polygon",
      "Workplane.close"]),
    ("Refine (select edges/faces first)", ["Workplane.fillet", "Workplane.chamfer", "Workplane.shell"]),
    ("Transform / boolean", ["Workplane.translate", "Workplane.rotate",
                             "Workplane.union", "Workplane.cut", "Workplane.intersect"]),
]

# Commonly-hallucinated method names + the CORRECT alternative. Only the ones genuinely absent from
# the live API (verified at generation time) are shown, so the list never lies.
_SUSPECT_METHODS = {
    "taper": "NO such method. To taper/contour a prism, LOFT between two rects of different size: "
             "cq.Workplane('XY').rect(80,80).workplane(offset=100).rect(40,40).loft()",
    "bend": "NO such method. To bend, SWEEP a profile along a curved spline path.",
    "twist": "NO such method. To twist, LOFT between rotated copies of a profile.",
    "emboss": "NO such method. Add/remove a shallow feature with union()/cut().",
    "round": "NO such method. Round edges with .edges(<selector>).fillet(r).",
    "dome": "NO such method. Use a partial sphere (revolve a profile) and boolean it.",
}


def _sig_line(kb: "KB", op_id: str) -> str:
    e = kb._by_id.get(op_id)
    if not e:
        return ""
    sig = e.get("signature") or ""
    argpart = sig[sig.find("("):] if "(" in sig else "(...)"
    summary = (e.get("summary") or "").strip().split("\n")[0][:70]
    return f"  {op_id}{argpart}  —  {summary}"


def _resolve_kb_path(kb_path: str) -> str:
    """The module default _KB_PATH points next to this file, but the KB actually ships in
    ../knowledge/. Try the given path, then the knowledge dir, then the env override."""
    cands = [kb_path,
             os.path.join(os.path.dirname(__file__), "..", "knowledge", "cadquery_kb.json"),
             os.environ.get("CADQUERY_KB", "")]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return kb_path


def build_idioms_skill(kb_path: str = _KB_PATH) -> str:
    """Return a COMPACT, TRUTHFUL CadQuery quick-reference: op NAMES per group (verified against the
    KB) + the selector grammar + a live-verified 'does NOT exist' list. Deliberately small (~1 KB)
    so the agent reads it in one step and spends its budget BUILDING, not reading. Full signatures
    are a LAZY lookup (cadquery_doc(id)) only when writing a custom step."""
    try:
        kb = KB(_resolve_kb_path(kb_path))
        by_name = getattr(kb, "_by_name", {})
        by_id = getattr(kb, "_by_id", {})
    except Exception:
        kb, by_name, by_id = None, {}, {}
    lines = [
        "### CadQuery quick-reference (real op names; call cadquery_doc(id) for a signature ONLY when "
        "writing a custom step). Prefer certified primitives + contour builders; custom is the exception.",
    ]
    for title, ops in _IDIOM_GROUPS:
        names = []
        for op in ops:
            bare = op.split(".")[-1]
            # keep only ops that genuinely exist in the KB (truthful), else skip
            if not by_id or op in by_id or bare.lower() in by_name:
                names.append(bare)
        if names:
            lines.append(f"{title}: " + ", ".join(names))
    lines += [
        'SELECTORS (.edges/.faces): ">Z" top | "<Z" bottom | ">X"/"<X"/">Y"/"<Y" sides | "|Z" vertical '
        'edges | combine with " and " e.g. ">Z and <Y".  e.g. result.edges("|Z").fillet(5)',
        "HOST-BUILT TECHNIQUES (supply NUMBERS, not code): revolved_profile (turned hub/shaft/vase), "
        "lofted_sections (contoured/tapered/blended body), swept_profile (rail/duct along a path), "
        "twisted_loft (one profile lofted through stations [z,radius,twist_deg,scale] -> blades/vanes/"
        "augers/drill flutes/twisted columns).",
        "MONOLITHIC body with REPEATED features (ONE fused single_solid: impeller/fan/turbine/gear/"
        "splined shaft): build the core (e.g. revolved_profile hub), cut holes (cylinder, operation "
        "cut), then ONE feature step (twisted_loft blade, or any primitive) carrying a RADIAL "
        "`pattern` {kind:radial,count:N,axis:z} with operation `join` — the kernel rotates + FUSES all "
        "N copies into ONE connected body. Don't hand-emit N steps; don't use `assembly` for a "
        "one-piece part.",
    ]
    absent = []
    try:
        import cadquery as _cq
        for name, fix in _SUSPECT_METHODS.items():
            if not hasattr(_cq.Workplane, name):
                absent.append((name, fix))
    except Exception:
        absent = list(_SUSPECT_METHODS.items())
    if absent:
        lines.append("DO NOT EXIST (common hallucinations, verified against the live API):")
        for name, fix in absent:
            lines.append(f"  Workplane.{name} -> {fix}")
    return "\n".join(lines)


def register(mcp, kb_path: str = _KB_PATH):
    """Attach the four KB tools to a FastMCP server (call from host_mcp.py)."""
    kb = KB(kb_path)

    @mcp.tool()
    def cadquery_browse() -> dict:
        """List CadQuery functional categories and how many operations each has.
        Call this first to see the landscape before searching."""
        return kb.browse()

    @mcp.tool()
    def cadquery_search(query: str, k: int = 8, kind: str = "all") -> dict:
        """Find CadQuery operations and worked examples relevant to `query`.
        Returns COMPACT hits (id + signature + summary). kind = api|examples|all.
        Then call cadquery_doc(id) or cadquery_example(id) for full detail."""
        return kb.search(query, k=k, kind=kind)

    @mcp.tool()
    def cadquery_doc(id_or_name: str) -> dict:
        """Full detail for ONE operation: exact signature, params, full docstring.
        Use the `id` from cadquery_search (e.g. 'Workplane.hole')."""
        return kb.doc(id_or_name)

    @mcp.tool()
    def cadquery_example(id_or_query: str) -> dict:
        """A full worked example with runnable code (a real composition to adapt)."""
        return kb.example(id_or_query)

    return mcp
