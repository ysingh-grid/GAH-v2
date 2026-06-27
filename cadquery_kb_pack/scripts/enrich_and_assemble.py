"""
enrich_and_assemble.py — add official functional-area categories to the API
entries and parse the worked-example gallery, then assemble the final KB.

Inputs : cadquery_api.json (from build_cadquery_kb.py), apireference.rst, examples.rst
Output : cadquery_kb.json  {version, api[], examples[], categories{}}
"""

import json
import re
import sys


def parse_apiref(path):
    """Map 'Workplane.box' / 'box' -> official functional-area category."""
    lines = open(path, encoding="utf-8").read().splitlines()
    cat_of = {}
    current = None
    i = 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        # header = text line underlined by --- or ===
        if line.strip() and re.fullmatch(r"[-=~^]{3,}", nxt.strip() or "x") and not line.startswith(".."):
            current = line.strip()
            i += 2
            continue
        if line.strip().startswith(".. autosummary") or line.strip().startswith(".. autoclass") \
                or line.strip().startswith(".. autofunction") or line.strip().startswith(".. automethod"):
            # collect following indented names
            j = i + 1
            while j < len(lines) and (lines[j].strip() == "" or lines[j][:1] in (" ", "\t")):
                nm = lines[j].strip().strip(":").strip()
                nm = re.sub(r"\s*\*\*!?\*\*", "", nm)  # strip the "!" marker
                if nm and current and not nm.startswith(".."):
                    cat_of[nm] = current               # full e.g. Workplane.box
                    cat_of[nm.split(".")[-1]] = current  # short e.g. box
                j += 1
            i = j
            continue
        i += 1
    return cat_of


def parse_examples(path):
    """Each example: a header, prose, then a `.. cadquery::` code block."""
    text = open(path, encoding="utf-8").read()
    lines = text.splitlines()
    examples = []
    i = 0
    n = len(lines)

    def header_at(k):
        if k + 1 < n and lines[k].strip() and re.fullmatch(r"[-=~^]{3,}", (lines[k + 1].strip() or "x")):
            t = lines[k].strip()
            if not t.startswith("..") and len(t) > 2:
                return t
        return None

    while i < n:
        title = header_at(i)
        if not title:
            i += 1
            continue
        i += 2
        desc, code, api_used = [], [], []
        # gather until next header
        while i < n and not header_at(i):
            s = lines[i]
            if s.strip().startswith(".. cadquery::"):
                i += 1
                # skip blank lines
                while i < n and lines[i].strip() == "":
                    i += 1
                # capture indented code block
                while i < n and (lines[i].strip() == "" or lines[i][:1] in (" ", "\t")):
                    if lines[i].strip():
                        code.append(lines[i].lstrip())
                    elif code:
                        code.append("")
                    i += 1
                continue
            if ":py:meth:`" in s or ":py:class:`" in s:
                api_used += re.findall(r":py:(?:meth|class):`([^`]+)`", s)
            elif s.strip() and not s.strip().startswith(("..", ":")):
                desc.append(s.strip())
            i += 1
        if code:
            examples.append({
                "id": "ex-" + re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"),
                "title": title,
                "description": re.sub(r"\s+", " ", " ".join(desc)).strip()[:500],
                "code": "\n".join(code).strip(),
                "api_used": sorted({a.replace("**!**", "").strip() for a in api_used}),
            })
    return examples


def main():
    api = json.load(open("cadquery_api.json"))["entries"]
    cat_of = parse_apiref("apireference.rst")
    enriched = 0
    for e in api:
        off = cat_of.get(e["id"]) or cat_of.get(e["name"])
        if off:
            e["category"] = off
            enriched += 1
    examples = parse_examples("examples.rst")

    # browse index: category -> [ids]
    cats = {}
    for e in api:
        cats.setdefault(e["category"], []).append(e["id"])

    kb = {
        "source": "cadquery (source AST) + official docs (apireference.rst, examples.rst)",
        "counts": {"api": len(api), "examples": len(examples), "categories": len(cats)},
        "categories": {k: sorted(v) for k, v in sorted(cats.items())},
        "api": api,
        "examples": examples,
    }
    json.dump(kb, open("cadquery_kb.json", "w"), indent=1)
    print(f"API entries: {len(api)} (re-categorized {enriched})")
    print(f"Examples:    {len(examples)}")
    print(f"Categories:  {len(cats)}")
    for k in sorted(cats):
        print(f"   {len(cats[k]):3d}  {k}")


if __name__ == "__main__":
    main()
