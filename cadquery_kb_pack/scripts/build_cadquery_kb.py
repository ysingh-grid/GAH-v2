"""
build_cadquery_kb.py — build a structured, searchable CadQuery knowledge base.

WHY AST, NOT HTML: the rendered docs are generated from the library's own
docstrings. Parsing the source with `ast` gives the complete, authoritative API
(every signature + docstring) without importing the native OCP kernel and without
fragile HTML scraping. Re-runnable on any installed CadQuery version.

Output: cadquery_kb.json  — a list of entries:
  {id, name, owner, kind, module, signature, summary, doc, params, returns, category, keywords}

Usage:  python build_cadquery_kb.py  /path/to/site-packages/cadquery  cadquery_kb.json
"""

import ast
import json
import os
import re
import sys

# Files that carry the API the RLM actually composes with, + a coarse category.
TARGET_CATEGORY = {
    "cq.py": "Workplane (fluent 3D/2D)",
    "sketch.py": "Sketch (2D)",
    "assembly.py": "Assembly",
    "selectors.py": "Selectors",
    "hull.py": "Hull",
    "func.py": "Functional API",
    "occ_impl/shapes.py": "Shapes (low-level: Solid/Face/Wire/Edge)",
    "occ_impl/geom.py": "Geometry (Vector/Plane/Location/Matrix)",
}


def _clean(sig_args: str) -> str:
    # drop a leading self/cls for readability
    return re.sub(r"^\s*(self|cls)\s*,\s*", "", sig_args).strip()


def _summary(doc: str) -> str:
    if not doc:
        return ""
    # first non-empty paragraph, whitespace-collapsed
    para = []
    for line in doc.strip().splitlines():
        if line.strip() == "" and para:
            break
        para.append(line.strip())
    return re.sub(r"\s+", " ", " ".join(para)).strip()


def _params(doc: str):
    """Pull Sphinx-style :param x: / :return: fields if present."""
    params, returns = [], None
    for m in re.finditer(r":param\s+(\w+)\s*:\s*(.+)", doc or ""):
        params.append({"name": m.group(1), "desc": m.group(2).strip()})
    rm = re.search(r":returns?:\s*(.+)", doc or "")
    if rm:
        returns = rm.group(1).strip()
    return params, returns


def _keywords(name: str, owner: str, summary: str):
    # split camelCase + snake_case names into search tokens
    toks = set()
    for w in re.findall(r"[A-Za-z][a-z]+|[A-Z]+(?![a-z])|\d+", name):
        toks.add(w.lower())
    toks.add(name.lower())
    toks.add(owner.lower())
    for w in re.findall(r"[a-zA-Z]{3,}", summary.lower()):
        toks.add(w)
    return sorted(toks)


def extract_file(path: str, rel: str, category: str):
    entries = []
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except Exception as e:
        print(f"  skip {rel}: {e}")
        return entries
    module = "cadquery." + rel[:-3].replace("/", ".")

    def emit(name, owner, kind, node):
        if name.startswith("_") and name != "__init__":
            return
        doc = ast.get_docstring(node) or ""
        try:
            args = _clean(ast.unparse(node.args))
        except Exception:
            args = ""
        ret = ""
        if getattr(node, "returns", None) is not None:
            try:
                ret = ast.unparse(node.returns)
            except Exception:
                ret = ""
        is_prop = any(getattr(d, "id", "") == "property" for d in node.decorator_list)
        sig = f"{name}({args})" + (f" -> {ret}" if ret else "")
        params, returns = _params(doc)
        summ = _summary(doc)
        entries.append({
            "id": f"{owner}.{name}" if owner else name,
            "name": name,
            "owner": owner,
            "kind": "property" if is_prop else kind,
            "module": module,
            "signature": sig,
            "summary": summ,
            "doc": doc.strip(),
            "params": params,
            "returns": returns,
            "category": category,
            "keywords": _keywords(name, owner, summ),
        })

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    emit(sub.name, node.name, "method", sub)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            emit(node.name, "", "function", node)
    return entries


def main():
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "cadquery_kb.json"
    all_entries = []
    for rel, cat in TARGET_CATEGORY.items():
        p = os.path.join(src, rel)
        if os.path.exists(p):
            got = extract_file(p, rel, cat)
            print(f"  {rel}: {len(got)} entries")
            all_entries.extend(got)
    # de-dup by id (keep the one with the longest docstring)
    best = {}
    for e in all_entries:
        if e["id"] not in best or len(e["doc"]) > len(best[e["id"]]["doc"]):
            best[e["id"]] = e
    entries = sorted(best.values(), key=lambda e: (e["category"], e["owner"], e["name"]))
    json.dump({"version": "extracted", "kind": "api", "entries": entries},
              open(out, "w"), indent=1)
    print(f"\nWROTE {out}: {len(entries)} API entries, "
          f"{len({e['owner'] for e in entries})} owners, "
          f"{len({e['category'] for e in entries})} categories")


if __name__ == "__main__":
    main()
