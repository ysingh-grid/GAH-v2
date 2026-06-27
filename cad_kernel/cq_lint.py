"""
cq_lint.py — fast, host-side lint of an LLM-authored custom `code_sketch` against the REAL CadQuery
API, with auto-RAG (KB) feedback. Runs BEFORE the (slower) isolated build subprocess so an invented
method is caught in milliseconds with a precise correction + a worked KB example — instead of after
a full build that returns one terse traceback (the failing run burned its budget on exactly this:
`Workplane.taper` and a wrong `spline` call).

Design for ZERO false positives (a false flag would block valid code, which is worse than a slow
traceback), so the lint only flags:
  (a) a DECLARED `cadquery_operations` op whose bare method name exists in neither the live CadQuery
      API nor the KB — the model itself claimed it is a CadQuery op, so absence = hallucination; and
  (b) a curated set of always-wrong CAD verbs (taper/bend/twist/emboss/round/dome) actually CALLED
      in the code AND confirmed absent from the live API.
Everything else is left to the build stage (whose tracebacks we ENRICH with KB docs). Fail-open:
any internal error in the linter returns None (never block on a lint bug).
"""

import ast
import re

_NAMESPACES = ("Workplane", "Sketch", "Solid", "Shape", "Edge", "Face", "Wire", "Vertex",
               "Vector", "Plane", "Assembly", "Compound", "Shell")

# Always-wrong CAD verbs → the correct alternative. Only used when confirmed absent from live cq.
_SUSPECT = {
    "taper": "no Workplane.taper() method — to taper/contour, LOFT between two rects of different "
             "size, OR pass taper=<deg> to extrude()/cutBlind().",
    "bend": "no bend() method — SWEEP a profile along a curved spline path.",
    "twist": "no twist() method — LOFT between rotated copies of a profile.",
    "emboss": "no emboss() method — union()/cut() a shallow feature.",
    "dome": "no dome() method — revolve a profile, or boolean a partial sphere.",
    "round": "no round() method — round edges with .edges(<selector>).fillet(r).",
}


def _cq_method_universe():
    """All public method/function names across the CadQuery namespaces (live introspection)."""
    import cadquery as cq
    names = set()
    for ns in _NAMESPACES:
        cls = getattr(cq, ns, None)
        if cls is not None:
            names |= {n for n in dir(cls) if not n.startswith("_")}
    names |= {n for n in dir(cq) if not n.startswith("_")}
    return names


def _called_methods(code: str):
    """Method names called as attributes (`.name(`), via AST (regex fallback on syntax error)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set(re.findall(r"\.([A-Za-z_]\w*)\s*\(", code or ""))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            out.add(node.func.attr)
    return out


def _load_kb():
    try:
        import os
        import sys
        here = os.path.dirname(__file__)
        tools = os.path.join(here, "..", "cadquery_kb_pack", "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        from cadquery_kb_tools import KB
        return KB()
    except Exception:
        return None


def _kb_example_snippet(kb, query):
    if kb is None:
        return ""
    try:
        hits = kb.search(query, k=1, kind="examples").get("examples") or []
        if not hits:
            return ""
        ex = kb.example(hits[0]["id"])
        code = (ex.get("code") or "")[:600]
        return f"\n  KB example '{ex.get('title')}':\n{code}" if code else ""
    except Exception:
        return ""


def lint_code_sketch(code: str, cadquery_operations=None, kb=None):
    """Return a precise error string if the code/declared-ops use a method that does NOT exist in
    CadQuery, else None. High precision (see module docstring). Fail-open."""
    try:
        universe = _cq_method_universe()
    except Exception:
        return None
    if kb is None:
        kb = _load_kb()
    kb_names = set()
    if kb is not None:
        try:
            kb_names = set(getattr(kb, "_by_name", {}).keys()) | set(getattr(kb, "_by_id", {}).keys())
        except Exception:
            kb_names = set()

    problems = {}  # name -> fix

    # (a) declared cadquery_operations that exist nowhere (live API or KB)
    for op in (cadquery_operations or []):
        bare = str(op).split(".")[-1].strip()
        if not bare or bare in universe:
            continue
        if bare.lower() in kb_names or str(op) in kb_names:
            continue
        problems[bare] = _SUSPECT.get(bare.lower(),
                                      f"'{op}' is not a real CadQuery operation — call "
                                      "cadquery_search() to find the correct one.")

    # (b) curated always-wrong verbs actually called in the code
    for name in _called_methods(code or ""):
        if name in _SUSPECT and name not in universe:
            problems[name] = _SUSPECT[name]

    if not problems:
        return None
    lines = ["custom code_sketch uses CadQuery method(s) that DO NOT EXIST (caught before build):"]
    for name, fix in problems.items():
        lines.append(f"  - '{name}': {fix}")
    # auto-RAG: attach ONE worked example to anchor the fix
    snippet = ""
    for name in problems:
        snippet = _kb_example_snippet(kb, "loft" if name.lower() == "taper" else name)
        if snippet:
            break
    return "\n".join(lines) + snippet


def enrich_build_error(stderr: str, cadquery_operations=None, kb=None):
    """Turn a terse custom-build traceback into actionable feedback: append the correct KB doc
    signature for each operation the step DECLARED it would use, so the model can self-correct.
    Returns the (possibly enriched) error string. Fail-open: returns stderr unchanged on any error."""
    base = (stderr or "").strip()
    try:
        if kb is None:
            kb = _load_kb()
        if kb is None or not cadquery_operations:
            return base
        hints = []
        for op in list(cadquery_operations)[:5]:
            try:
                e = kb.doc(op) if hasattr(kb, "doc") else None
            except Exception:
                e = None
            if e and e.get("signature"):
                hints.append(f"  {e['id']}{e['signature'][e['signature'].find('('):]}  — {(e.get('summary') or '')[:60]}")
        if hints:
            return base + "\n  CadQuery KB — correct signatures for the operations this step declared:\n" + "\n".join(hints)
        return base
    except Exception:
        return base
