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

_KB_PATH = os.environ.get("CADQUERY_KB", os.path.join(os.path.dirname(__file__), "cadquery_kb.json"))


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
