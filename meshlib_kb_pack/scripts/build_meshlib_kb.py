"""
build_meshlib_kb.py — build a CURATED MeshLib knowledge base by introspection.

MeshLib's Python API (mrmeshpy) is a compiled pybind11 module, so there is no
source to AST-parse — but every symbol carries a docstring with its real
signature. We introspect, then CURATE to the verification-relevant subset
(mrmeshpy has ~2766 symbols; a verifier needs ~100, not all of them).

The KB grounds the FIXED battery you author and any ADVISORY checks the RLM
proposes. It is NOT a license for the RLM to choose the verdict's checks.

Output: meshlib_kb.json  {counts, categories, api:[...]}
"""

import inspect
import json
import re
from pathlib import Path

from meshlib import mrmeshpy as mm

# verification-relevant categories -> name patterns (module-level callables)
CATEGORIES = {
    "validity / self-intersection": r"(SelfColl|SelfInter|selfColl|selfInter|fixSelfInter|degenerate|NonManifold|nonManifold)",
    "components / connectivity": r"(Components|getAllComponents|largestComponent|getComponent)",
    "holes / watertight": r"(findHole|fillHole|holeDirArea|HoleRepresent|boundary)",
    "measurement": r"(^computeBoundingBox|surfaceArea|^volume|MeshVolume|projectArea|signedDistance|findMaxDistance)",
    "boolean": r"(^boolean$|doBooleanOperation|^selfBoolean$|BooleanOperation|BooleanResult)",
    "repair / fix": r"(fixUndercut|removeDegenerate|uniteCloseVertices|fixMultipleEdges|removeSpikes|fillHoles)",
    "distance / compare": r"(findSignedDistance|projectPoint|findGeodesic|HausdorffDist|compareMeshes)",
    "io": r"(^loadMesh$|^saveMesh$|^topologyFromTriangles$)",
}

# key classes whose METHODS we also surface (the battery calls these)
CLASSES = ["Mesh", "MeshTopology", "MeshComponents", "MeshPart"]


def first_sig(doc: str):
    if not doc:
        return "", ""
    lines = [l for l in doc.splitlines() if l.strip()]
    sig = ""
    for l in lines:
        if "(" in l and ")" in l:
            sig = l.strip(); break
    summary = ""
    for l in lines:
        if "(" not in l and not l.strip().startswith(("Overloaded", "1.", "2.")):
            summary = l.strip(); break
    return sig, summary


def entry(name, owner, obj, category):
    doc = inspect.getdoc(obj) or ""
    sig, summary = first_sig(doc)
    return {
        "id": f"{owner}.{name}" if owner else name,
        "name": name, "owner": owner,
        "kind": "method" if owner else "function",
        "category": category,
        "signature": sig or f"{name}(...)",
        "summary": summary[:200],
        "doc": doc[:1200],
        "keywords": sorted(set(re.findall(r"[a-z]{3,}", (name + " " + summary).lower()))),
    }


def main():
    out = []
    seen = set()
    names = [n for n in dir(mm) if not n.startswith("_")]
    # module-level callables by category
    for cat, pat in CATEGORIES.items():
        for n in names:
            if n in seen:
                continue
            if re.search(pat, n):
                obj = getattr(mm, n)
                if callable(obj):
                    out.append(entry(n, "", obj, cat)); seen.add(n)
    # class methods
    for cls_name in CLASSES:
        cls = getattr(mm, cls_name, None)
        if cls is None:
            continue
        for mname, mobj in inspect.getmembers(cls):
            if mname.startswith("_") or not callable(mobj):
                continue
            if re.search(r"(volume|area|boundingBox|topology|component|hole|valid|closed|"
                         r"numberOf|points|faces|signedDistance|projArea|intersect)", mname, re.I):
                key = f"{cls_name}.{mname}"
                if key not in seen:
                    out.append(entry(mname, cls_name, mobj, f"{cls_name} method"))
                    seen.add(key)

    cats = {}
    for e in out:
        cats.setdefault(e["category"], []).append(e["id"])
    kb = {"source": "meshlib.mrmeshpy introspection (curated to verification-relevant subset)",
          "counts": {"api": len(out), "categories": len(cats)},
          "categories": {k: sorted(v) for k, v in sorted(cats.items())},
          "api": sorted(out, key=lambda e: (e["category"], e["id"]))}
    outp = Path(__file__).resolve().parent.parent / "knowledge" / "meshlib_kb.json"
    outp.write_text(json.dumps(kb, indent=1))
    print(f"wrote {outp}: {len(out)} entries, {len(cats)} categories")
    for k in sorted(cats):
        print(f"  {len(cats[k]):3d}  {k}")


if __name__ == "__main__":
    main()
