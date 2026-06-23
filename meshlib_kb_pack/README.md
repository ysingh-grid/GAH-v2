# MeshLib KB pack — grounding the verifier

A curated, searchable knowledge base of MeshLib's verification-relevant Python API,
built by **introspection** of `meshlib.mrmeshpy` (it is compiled pybind11, so there is
no source to parse — but every symbol carries its signature + docstring). Curated to
~121 entries from MeshLib's ~2766 symbols: validity/self-intersection, components,
holes/watertight, measurement, boolean, repair, distance, and the key class methods.

Note: meshlib.io docs are Doxygen/**C++** — the wrong surface for the Python calls the
verifier makes. Introspection gives the actual Python API, so it is the right source.

Contents: `knowledge/meshlib_kb.json`, `tools/meshlib_kb_tools.py` (`meshlib_browse /
meshlib_search / meshlib_doc` + `register(mcp)`), `scripts/build_meshlib_kb.py` (rebuild
on any MeshLib version), `skills/meshlib_verify.md`.

Its role: **ground the FIXED battery you author** (`cad_kernel/verify.py`) and the
**advisory** checks the RLM may propose — never to let the RLM choose the verdict's checks.
