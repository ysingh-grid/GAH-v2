# SKILL: freeform planning via the CadQuery KB (loaded on demand)

Use this when no primitive can represent a shape. Do NOT guess CadQuery — look it up.

1. `cats = await mcp_call("host_tools", "cadquery_browse")` — see the operation landscape.
2. `hits = await mcp_call("host_tools", "cadquery_search", query="<what you need, e.g. 'revolve a profile'>")` — compact hits.
3. For each op you'll use: `doc = await mcp_call("host_tools", "cadquery_doc", id_or_name="Workplane.revolve")` — use its EXACT signature; never invent arguments.
4. `ex = await mcp_call("host_tools", "cadquery_example", id_or_query="revolve")` — adapt a real composition.
5. Emit a `custom` step with **exactly** these parameter keys (no others, no aliases):

```python
{
    "sequence_id": N,
    "name": "...",
    "primitive_type": "custom",
    "parameters": {
        "shape_description": "plain English: what this step builds",          # str, required
        "cadquery_operations": ["Workplane.revolve", "Workplane.ellipseArc"], # list[str], required — exact ids from KB
        "code_sketch": "import cadquery as cq\nresult = cq.Workplane('XY')...",# str, required — binds `result`
        "declared_dimensions": {"outer_dia_mm": 80.0, "height_mm": 120.0}    # dict[str,float], required (can be {})
    },
    "operation": "new",    # or join / cut / intersect
    "position": [0, 0, 0],
    "rotation": [0, 0, 0],
    "rationale": "Why no primitive can represent this shape, so a freeform step is required"
}
```

**WRONG** (will be rejected by Pydantic):
```python
"parameters": {"description": "my shape"}          # wrong key name
"parameters": {"shape": "star", "arms": 5}         # invented keys
"parameters": {"shape_description": "..."}         # missing cadquery_operations, code_sketch
```

6. A `custom` step ships `needs_review` — sound + right-sized can be checked later, but "the right object" cannot be certified. Do not claim otherwise.
