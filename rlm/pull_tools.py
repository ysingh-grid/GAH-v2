# mypy: ignore-errors
# These are PULL TOOLS executed inside the RLM's Pyodide sandbox via
# inspect.getsource. Each function must be self-contained (imports inside the
# body, no module-level deps) and use only builtin annotations (bare `dict`,
# `list[str]`) because `typing.Any` is not importable in the REPL. mypy --strict
# would demand `dict[str, Any]`, which would NameError at REPL exec time, so we
# exempt this one file from type-checking by design.


def list_primitives() -> list[str]:
    """Return the keys of every primitive in the catalog.

    Tool the RLM calls to discover what shapes it's allowed to plan with.
    """
    """
    INFO !!!!! :os.environ["DTCM_BACKEND_URL"] — the backend's address is injected via
 fast-rlm's env_variables, not hardcoded. Sandbox can't guess 127.0.0.1:8001;
  we hand it in. Bracket access (not .get) so a missing var fails loud.
    """
    import os

    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    resp = requests.get(f"{base}/internal/list-primitives", timeout=10)

    resp.raise_for_status()
    return list(resp.json().keys())


def lookup_primitive(key: str) -> dict:
    """Return the full spec of one primitive: params, verification, template.

    The RLM calls this once it has picked a shape and needs its real
    parameter names and constraints to fill the plan correctly.
    """
    import os

    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    resp = requests.get(
        f"{base}/internal/lookup-primitive",
        params={"key": key},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def list_skills() -> list[str]:
    """Return the names of every reasoning-guide skill available.

    The RLM's live catalog of guides. Playbook names the core read-order, but
    this reads the skills dir directly — so newly-added guides are discoverable
    even before the playbook mentions them.
    """
    import os

    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    resp = requests.get(f"{base}/internal/list-skills", timeout=10)
    resp.raise_for_status()
    return resp.json()


def read_skill(name: str) -> str:
    """Return the full markdown text of one skill guide.

    Call after list_skills (or with a name from the playbook) to read a guide's
    reasoning instructions into your working context.
    """
    import os

    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    resp = requests.get(
        f"{base}/internal/read-skill",
        params={"name": name},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.text

# --- DISABLED WEB SEARCH TEMPORARILY ---
def web_search(query: str) -> dict: 
    """Search the web for a real-world measurement or standard.

    PERMISSION-GATED: only callable after the USER has explicitly granted web
    access this turn. If you call it without permission it RAISES — do not call it
    speculatively. Instead, ask the user first (action="ask_user") and offer a
    "Search the web for ..." option; only call this once they choose it.

    Returns {"query", "answer", "sources": [{"title", "uri"}]}; an "error" key
    (and empty answer) means the lookup found nothing — treat that as "ask the user".
    """
    import os

    import requests

    # Code-level permission gate. The backend sets DTCM_WEB_SEARCH_ALLOWED=1 only
    # when the user's latest message granted web access; otherwise this raises so
    # the model physically cannot search without consent (prompt rules alone leak).
    if os.environ.get("DTCM_WEB_SEARCH_ALLOWED") != "1":
        raise PermissionError(
            "web_search is not permitted: the user has not granted web access this "
            "turn. Ask the user first (action='ask_user') and offer a 'Search the "
            "web for ...' option; only search after they explicitly choose it."
        )

    base = os.environ["DTCM_BACKEND_URL"]
    resp = requests.get(f"{base}/internal/web-search", params={"q": query}, timeout=30)
    resp.raise_for_status()
    return resp.json()

# --- DISABLED WEB SEARCH TEMPORARILY ---

def list_kb_index() -> dict:
    """Return the compact index of what is available in both KBs.

    Call this ONCE in Step 1 alongside list_primitives(). It returns a menu
    of section slugs and one-line descriptions — NOT the content itself.
    Use the slugs to decide which sections to fetch with fetch_kb_sections().

    This mirrors list_primitives() → lookup_primitive() for the KB:
      list_kb_index()   →  see the menu
      fetch_kb_sections() →  read what you need

    Returns:
        {
          "cadquery": {slug: description, ...},   # CadQuery API categories
          "forgecad": {slug: description, ...},   # ForgeCAD API sections
        }
    """
    import os

    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    resp = requests.get(f"{base}/internal/kb-index", timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_kb_sections(keys: list[str]) -> dict:
    """Fetch specific KB sections by slug keys from list_kb_index().

    Call this in Step 1 AFTER list_kb_index() — pick only the slugs that are
    relevant to the current request. Each fetched section is ≤800 chars.

    Args:
        keys: List of slug strings from list_kb_index(), e.g.
              ["3d-operations", "revolve", "sweep"].
              Mix of cadquery and forgecad slugs is fine.
              Fetch ≤5 sections to keep token cost bounded.

    Returns:
        {slug: content_snippet} for each found key. Missing keys are omitted.
    """
    import os

    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    resp = requests.get(
        f"{base}/internal/kb-fetch",
        params={"keys": ",".join(keys)},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def lookup_design_reference(query: str) -> dict:
    """Look up standard dimensions + adaptable CSG recipes for a design task.

    Call this BEFORE inventing geometry or web-searching. It returns, compactly:
      - "fastener_dims": metric clearance / tap / counterbore tables (mm). Use
        these for any bolt/screw hole instead of guessing a diameter.
      - "recipes": a few known-good step templates (e.g. through_hole,
        counterbored_hole, bolt_circle, rib, mounting_plate) matched to your
        query. Each recipe's "steps" are PrimitivePlan fragments with <...>
        placeholders — ADAPT them (fill real mm values + positions) and inline
        them into your own steps. Recipes use only real library primitives, so an
        adapted recipe needs no special handling.

    Returns {"fastener_dims": {...}, "recipes": {name: {description, steps, ...}}}.
    Grounding a plan in a retrieved recipe beats composing CSG from scratch.
    """
    import os

    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    resp = requests.get(
        f"{base}/internal/design-reference",
        params={"q": query},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


async def delegate_features(features: list[dict], shared_frame: dict) -> list[list[dict]]:
    """Delegate independent solids or body features to parallel child agents.

    Call this tool when planning compound parts (e.g. box + lid, hub + spokes + rim).
    It spawns parallel child sub-agents with clean context windows, runs them
    simultaneously, and returns their generated CSG step lists.

    Args:
        features: List of feature specifications. Each dictionary should contain:
                  - "name": str (e.g. "lid", "spoke")
                  - "operation": str ("base", "union", "cut", or "intersect")
                  - "placement": list[float] (absolute [x, y, z] position)
                  - "candidate_primitives": list[str] (2-4 catalog keys to consider)
                  - "notes": str (optional overlap or sizing details)
        shared_frame: Dictionary defining shared skeleton dimensions (radii, planes,
                      bolt circles) so child parts align correctly. Pass {} if parts
                      are completely independent solids.

    Returns:
        A list of step-lists (one list of CSG step dicts per feature), in the exact
        order requested. Flatten these into your main steps array.
    """
    _llm_query = globals()["llm_query"]
    _batch_query = globals()["batch_llm_query"]
    _lookup_prim = globals()["lookup_primitive"]
    _lookup_ref = globals()["lookup_design_reference"]

    step_schema = {"type": "array", "items": {"type": "object"}}
    child_tools = [_lookup_prim, _lookup_ref]

    queries = []
    for feat in features:
        q_context = {
            "task": (
                "Build ONLY this feature/solid IN THE SHARED FRAME given. Use the "
                "absolute position + operation provided — do NOT change any shared "
                "anchor. Use lookup_primitive(key) for exact param names. Return a "
                "JSON list of step objects: {id, primitive, operation, parameters, "
                "position:[x,y,z], orientation:[rx,ry,rz], pattern?}."
            ),
            "feature": feat,
            "shared_frame": shared_frame,
            "candidate_primitives": feat.get("candidate_primitives", []),
        }
        queries.append(_llm_query(q_context, step_schema, tools=child_tools))

    results = await _batch_query(*queries)
    return list(results)

