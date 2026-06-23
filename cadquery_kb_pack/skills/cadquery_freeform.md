# SKILL: freeform geometry via the CadQuery knowledge base

Use this ONLY when no primitive fits the requested shape. You do NOT know
CadQuery by heart and you must NOT guess its API — look it up, then write code
the geometry server can build and the verifier can fact-check.

Procedure:
1. See the landscape, then search for the operations you need:
   - `cats = await mcp_call("cadkb", "cadquery_browse")`
   - `hits = await mcp_call("cadkb", "cadquery_search", query="revolve a profile")`
   Hits are compact (id + signature + summary). Pick the ops you need.
2. Get each op's EXACT call signature before using it:
   - `d = await mcp_call("cadkb", "cadquery_doc", id_or_name="Workplane.revolve")`
   Use `d["signature"]` and `d["params"]` verbatim — never invent arguments.
3. See how ops are composed in a real example:
   - `ex = await mcp_call("cadkb", "cadquery_example", id_or_query="revolve")`
   Adapt `ex["code"]`; don't copy blindly.
4. Write the CadQuery code AND a declared contract (the key dimensions you believe
   you built). Send both to the geometry server's build tool.
5. The server builds it; `inspect()` measures it. The VERDICT is inspect's, not
   yours. Freeform geometry can be confirmed a SOUND, RIGHT-SIZED solid, but it
   CANNOT be certified as "the right object" — it ships as NEEDS_REVIEW and is
   logged as a promotion candidate. Do not claim CERTIFIED.

Rules: never guess a signature — `cadquery_doc` it first. Stay within the ops you
looked up. Declare your key dimensions so inspect can audit declared-vs-measured.
