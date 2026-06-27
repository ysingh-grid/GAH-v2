# CadQuery Knowledge Base pack

Gives the RLM the *whole* of CadQuery in a form it can actually use: a searchable
knowledge base of every operation (exact signatures + docstrings) plus the worked
example gallery, behind four retrieval tools. This is the fuel for the **freeform
path** — when no primitive fits, the RLM looks up the CadQuery ops it needs,
composes code, and the geometry server builds + fact-checks it.

## Why a KB, not "paste the docs into the prompt"
Dumping all of CadQuery into context bloats it and *lowers* answer quality. fast-rlm
is built to RETRIEVE from a corpus, so the KB is searchable and the RLM pulls only
the few ops a given shape needs. Two levels keep context small:
`search/browse` -> compact hits; `doc/example` -> full detail for one chosen id.

## Why built from source, not scraped HTML
The rendered docs are generated from the library's own docstrings. `scripts/`
parses the CadQuery *source* with `ast` (no native OCP import, no fragile HTML),
then enriches with the official functional-area categories and the example gallery
from the docs repo. Re-runnable on any CadQuery version.

## Contents
```
knowledge/cadquery_kb.json     # 523 API entries + 33 worked examples + 17 categories
tools/cadquery_kb_tools.py     # KB class + register(mcp) -> 4 MCP tools
scripts/build_cadquery_kb.py   # AST extractor   (step 1)
scripts/enrich_and_assemble.py # categories + examples assembler (step 2)
skills/cadquery_freeform.md    # tells the RLM how to use the KB in the freeform path
```

## The four tools the RLM gets
- `cadquery_browse()` — categories + counts (see what exists first).
- `cadquery_search(query, k, kind)` — compact hits (id + signature + summary). kind=api|examples|all.
- `cadquery_doc(id_or_name)` — full detail for ONE op (exact signature, params, docstring).
- `cadquery_example(id_or_query)` — a full worked example with runnable code.

## Integrate into v3_capstone_ds (2 steps)
1. Copy `knowledge/cadquery_kb.json` and `tools/cadquery_kb_tools.py` into the repo;
   add `skills/cadquery_freeform.md`.
2. In `tools/host_mcp.py`, after you build your FastMCP server, register the tools:
   ```python
   from tools.cadquery_kb_tools import register as register_cadkb
   register_cadkb(mcp, kb_path="knowledge/cadquery_kb.json")
   ```
   Now the RLM reaches them via `await mcp_call("cadkb", "cadquery_search", query=...)`
   (use whatever name you gave the server). Add the freeform skill to the run when
   the primitive lookup misses.

## Rebuild (any CadQuery version)
```bash
pip install cadquery --no-deps          # source only; no native kernel needed
python scripts/build_cadquery_kb.py  $(python -c "import os,importlib.util as u;print(os.path.dirname(u.find_spec('cadquery').origin))")  cadquery_api.json
# fetch apireference.rst + examples.rst from the CadQuery docs repo, then:
python scripts/enrich_and_assemble.py   # -> cadquery_kb.json
```

## The discipline (don't lose this)
Freeform CadQuery output is **fact-checked, never auto-certified**. The KB lets the
RLM build shapes you have no primitive for, but a freeform solid is only provably
*sound and right-sized*, not provably *the right object*. It ships NEEDS_REVIEW and
is logged as a promotion candidate — recurring shapes graduate into primitives.
