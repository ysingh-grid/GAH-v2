"""meshlib_kb_tools.py — retrieval over the curated MeshLib KB.

Two levels (search -> doc) so context stays small. Deterministic keyword search.
Grounds the FIXED battery you author and the ADVISORY checks the RLM proposes —
it never lets the RLM choose the verdict's checks.
"""
import json
import os
import re

_KB = os.environ.get("MESHLIB_KB",
                     os.path.join(os.path.dirname(__file__), "..", "knowledge", "meshlib_kb.json"))


def _tok(s):
    return [t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) > 1]


class KB:
    def __init__(self, path=_KB):
        d = json.load(open(os.path.abspath(path), encoding="utf-8"))
        self.api = d["api"]
        self.categories = d["categories"]
        self._by_id = {e["id"]: e for e in self.api}

    def browse(self):
        return {c: len(v) for c, v in self.categories.items()}

    def search(self, query, k=8):
        q = _tok(query)
        scored = []
        for e in self.api:
            name = e["name"].lower()
            kw = set(e.get("keywords", []))
            s = sum((10 if t == name else 4 if t in name else 0) +
                    (3 if t in kw else 0) +
                    (1 if t in e["summary"].lower() else 0) +
                    (1 if t in e["category"].lower() else 0) for t in q)
            if s > 0:
                scored.append((s, e))
        scored.sort(key=lambda x: -x[0])
        return [{"id": e["id"], "signature": e["signature"], "summary": e["summary"][:160],
                 "category": e["category"]} for _, e in scored[:k]]

    def doc(self, id_or_name):
        e = self._by_id.get(id_or_name)
        if not e:
            e = next((x for x in self.api if x["name"].lower() == id_or_name.lower()), None)
        if not e:
            raise ValueError(f"no MeshLib entry for {id_or_name!r} (try meshlib_search)")
        return e


def register(mcp, kb_path=_KB):
    kb = KB(kb_path)

    @mcp.tool()
    def meshlib_browse() -> dict:
        """MeshLib verification categories and how many functions each has."""
        return kb.browse()

    @mcp.tool()
    def meshlib_search(query: str, k: int = 8) -> list:
        """Find MeshLib functions/methods relevant to a check you want to express.
        Returns compact hits (id + signature + summary). For grounding the fixed
        battery and proposing ADVISORY checks — not for choosing the verdict."""
        return kb.search(query, k=k)

    @mcp.tool()
    def meshlib_doc(id_or_name: str) -> dict:
        """Full signature + docstring for one MeshLib function/method."""
        return kb.doc(id_or_name)

    return mcp
