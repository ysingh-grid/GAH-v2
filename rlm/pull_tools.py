# mypy: ignore-errors
# These are PULL TOOLS executed inside the RLM's Pyodide sandbox via
# inspect.getsource. Each function must be self-contained (imports inside the
# body, no module-level deps) and use only builtin annotations (bare `dict`,
# `list[str]`) because `typing.Any` is not importable in the REPL. mypy --strict
# would demand `dict[str, Any]`, which would NameError at REPL exec time, so we
# exempt this one file from type-checking by design.


def list_primitives() -> list[str]:
    """Return every primitive key available in the shape catalog.

    WHEN: Call this as your FIRST data-gathering action (step 1), before any
    planning. You cannot select primitives without knowing the vocabulary.

    WHY: The catalog defines your vocabulary — the set of shapes you're
    allowed to plan with. Planning with a shape not in this list causes
    a downstream compile failure (unknown primitive key).

    OUTPUT: list[str] — e.g. ["box", "cone", "cylinder", "sphere", ...]
    NEXT: After listing, call lookup_primitive(key) on the 1-3 shapes that
    match your construction tree to get their exact parameter schemas.
    Do NOT call lookup_primitive on every key — only what you plan to use.
    """
    import os
    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    url = f"{base}/internal/list-primitives"
    for _attempt in range(2):
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            return list(resp.json().keys())
        except Exception as _e:
            if _attempt == 0:
                continue
            raise RuntimeError(
                f"list_primitives: backend unreachable at {url!r} ({_e}). "
                "Check DTCM_BACKEND_URL."
            ) from None


def lookup_primitive(key: str) -> dict:
    """Return the full specification of one primitive: description, parameter
    schema with types and constraints, verification formulas, and template.

    WHEN: Call AFTER list_primitives(). Once you've matched a shape from the
    vocabulary to a step in your construction tree, pull its exact spec to
    fill the plan correctly.

    WHY: The catalog menu only shows keys and one-line descriptions —
    insufficient to build a valid step. You need the real parameter names,
    types, and required fields to avoid guessing (which causes compile
    failures downstream).

    ARGS:
        key: Exact catalog key from list_primitives(), e.g. "cone", "box"

    RETURNS: {description, parameters: {name: {type, required, default,
    constraints}}, verification: {volume_formula, min_faces}, template: str}

    ERRORS: ValueError means the key is not in the catalog — pick a different
    key from list_primitives().
    """
    import os
    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    url = f"{base}/internal/lookup-primitive"
    for _attempt in range(2):
        try:
            resp = requests.get(url, params={"key": key}, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as _e:
            if _attempt == 0:
                continue
            raise RuntimeError(
                f"lookup_primitive({key!r}): backend unreachable at {url!r} ({_e})."
            ) from None


def list_skills() -> list[str]:
    """Return the names of every reasoning skill available for loading.

    WHEN: Rarely needed — the playbook already lists the core read-order.
    Call only if you suspect a skill exists that's not in playbook, or if
    you're debugging and need to know what's available.

    WHY: Skills are loaded by name via read_skill(). This lists the menu
    so you can discover newly-added or optional skills not referenced in
    the playbook's read-order table.

    OUTPUT: list[str] — e.g. ["playbook", "decompose_and_select", ...]
    NEXT: Pass any returned name to read_skill(name) to load it.
    """
    import os
    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    url = f"{base}/internal/list-skills"
    for _attempt in range(2):
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as _e:
            if _attempt == 0:
                continue
            raise RuntimeError(
                f"list_skills: backend unreachable at {url!r} ({_e})."
            ) from None


def read_skill(name: str) -> str:
    """Load one skill guide into REPL memory and return a memory pointer.

    WHEN: Your FIRST action MUST be read_skill('playbook'). After that,
    follow the skill read-order the playbook gives you. Load on-demand
    skills (debug_cadquery, refine_from_feedback) only when their trigger
    condition is met (code failure, prior_feedback present).

    WHY: Skills teach REASONING PATTERNS, not pipeline steps. Each skill is
    a self-contained module that teaches you HOW to think about one aspect
    of geometry (decomposition, dimensions, verification, debugging). Don't
    dump skills into your context window — pull only what you need, one at
    a time.

    ARGS:
        name: Skill name without extension, e.g. "playbook", "compute_dimensions"

    SIDE EFFECTS: Stores content in `_SKILLS[name]` and `context['skills'][name]`.
    Query with Python for specific sections instead of printing the whole content.

    RETURNS: Memory pointer string — do NOT print the full skill text.
    """
    import os
    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    url = f"{base}/internal/read-skill"
    for _attempt in range(2):
        try:
            resp = requests.get(url, params={"name": name}, timeout=10)
            resp.raise_for_status()
            text = resp.text
            break
        except Exception as _e:
            if _attempt == 0:
                continue
            raise RuntimeError(
                f"read_skill({name!r}): backend unreachable at {url!r} ({_e})."
            ) from None

    g = globals()
    if "_SKILLS" not in g:
        g["_SKILLS"] = {}
    g["_SKILLS"][name] = text
    if "context" in g and isinstance(g["context"], dict):
        g["context"].setdefault("skills", {})[name] = text

    return (
        f"[MEMORY_LOADED] Skill '{name}' ({len(text)} chars) stored in "
        f"`_SKILLS['{name}']` (and `context['skills']['{name}']`). "
        "Do NOT print. Query or slice in Python."
    )


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
    """Return the compact section menu of available knowledge-base content.

    WHEN: Call ONCE in Step 1 alongside list_primitives(). This gives you
    the table of contents — NOT the full content.

    WHY: Mirrors list_primitives()→lookup_primitive() for the KB. See the
    menu first (cheap, ~200 tokens), then fetch only the sections relevant
    to the current design task. Fetching all sections would waste tokens
    on CAD concepts you don't need for this specific shape.

    RETURNS: {"cadquery": {slug: description, ...},
              "forgecad": {slug: description, ...}}
    NEXT: Pick ≤5 relevant slugs and call fetch_kb_sections(slugs) to load
    their content into `_KB[slug]`.
    """
    import os
    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    url = f"{base}/internal/kb-index"
    for _attempt in range(2):
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as _e:
            if _attempt == 0:
                continue
            raise RuntimeError(
                f"list_kb_index: backend unreachable at {url!r} ({_e})."
            ) from None


def fetch_kb_sections(keys: list[str]) -> dict:
    """Fetch specific KB sections by slug and store them in REPL memory.

    WHEN: Call AFTER list_kb_index(). Pick ≤5 slugs relevant to your current
    design task. This is the "read what you need" step after seeing the menu.

    WHY: Each section is ≤800 chars of focused CadQuery/ForgeCAD API reference.
    Fetching them selectively keeps your context window small. Never fetch
    sections you won't use for this specific shape.

    ARGS:
        keys: List of slug strings, e.g. ["3d-operations", "revolve"].
              Mix cadquery and forgecad slugs freely. Max 5 recommended.

    SIDE EFFECTS: Stores content in `_KB[slug]` and `context['kb_cache'][slug]`.

    RETURNS: {slug: memory_pointer} — query `_KB['slug']` in Python to read.
    """
    import os

    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    url = f"{base}/internal/kb-fetch"
    for _attempt in range(2):
        try:
            resp = requests.get(url, params={"keys": ",".join(keys)}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as _e:
            if _attempt == 0:
                continue
            raise RuntimeError(
                f"fetch_kb_sections({keys!r}): backend unreachable at {url!r} ({_e})."
            ) from None

    g = globals()
    if "_KB" not in g:
        g["_KB"] = {}
    if "context" in g and isinstance(g["context"], dict):
        g["context"].setdefault("kb_cache", {})

    handles = {}
    for k, content in data.items():
        g["_KB"][k] = content
        if "context" in g and isinstance(g["context"], dict):
            g["context"]["kb_cache"][k] = content
        handles[k] = f"[MEMORY_LOADED] {len(content)} chars stored in `_KB['{k}']`"

    return handles


def lookup_design_reference(query: str) -> dict:
    """Look up standard engineering dimensions and CSG recipes for a design.

    WHEN: Call BEFORE inventing dimensions or web-searching. If the user
    mentions fasteners (M3, M6, etc.), fits, or standard mechanical
    interfaces, pull the reference data FIRST rather than guessing.

    WHY: Metric clearance tables and proven CSG templates are authoritative.
    Guessing a bolt-hole diameter wastes a full loop cycle when the verifier
    catches it. This tool gives you the ground truth in one call.

    ARGS:
        query: Free-form string, e.g. "m6 clearance", "flange recipe", "bearing seat"

    SIDE EFFECTS: Stores data in `_REF['fastener_dims']` and `_REF['recipes']`.
    Query `_REF['fastener_dims']` for metric clearance tables; query
    `_REF['recipes']` for adaptable CSG step templates.

    RETURNS: Dict of memory pointers — query the stored values in Python.
    """
    import os

    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    url = f"{base}/internal/design-reference"
    for _attempt in range(2):
        try:
            resp = requests.get(url, params={"q": query}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as _e:
            if _attempt == 0:
                continue
            raise RuntimeError(
                f"lookup_design_reference({query!r}): backend unreachable at {url!r} ({_e})."
            ) from None

    g = globals()
    if "_REF" not in g:
        g["_REF"] = {}
    if "context" in g and isinstance(g["context"], dict):
        g["context"].setdefault("design_ref", {})

    handles = {}
    for k, val in data.items():
        g["_REF"][k] = val
        if "context" in g and isinstance(g["context"], dict):
            g["context"]["design_ref"][k] = val
        if isinstance(val, dict):
            summary = f"{len(val)} keys: {list(val.keys())[:5]}"
        elif isinstance(val, list):
            summary = f"{len(val)} items"
        else:
            summary = f"{type(val).__name__}"
        handles[k] = f"[MEMORY_LOADED] stored in `_REF['{k}']` ({summary})"

    return handles


async def delegate_features(features: list[dict], shared_frame: dict) -> list[list[dict]]:
    """Spawn parallel child agents for independent solids in a multi-solid assembly.

    WHEN: Call ONLY for Case A (genuinely independent solids — see
    decompose_and_select skill). Examples: box+lid, bolt+nut, blade+handle.
    Never call for features of a single connected body — plan those inline.

    WHY: Independent solids need their own clean context to avoid cross-
    contamination (lid parameters leaking into box parameters). Parallel
    children run simultaneously, saving turns vs. sequential planning.
    The shared_frame enforces interface consistency (same bolt circle,
    same mating plane) across independently-designed parts.

    ARGS:
        features: [{name, operation, placement: [x,y,z],
                   candidate_primitives: [2-4 keys], notes?}, ...]
        shared_frame: {shared radii, planes, bolt positions} or {} for
                      completely independent parts.

    RETURNS: List of step-lists — one per feature in input order.
    Flatten these into your main plan's steps array before FINAL.
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


async def delegate_stage(stage: str, skill_name: str, payload: dict) -> dict:
    """ISOLATED / NOT IN THE TOOLSET — kept for reference, do not re-add blindly.

    Measured harmful: a planning stage has tiny context, so spawning a full child
    agent per stage is pure overhead (drove a single-solid part to >1M tokens /
    runaway). Inline reasoning in the root is cheaper. Delegation is reserved for
    delegate_features (independent SOLIDS in a multi-solid assembly). See
    runtime/planner._PLANNER_TOOLS for why this is excluded.

    Run ONE reasoning stage in an isolated child agent — keep the root tiny.

    This is the by-reference workhorse. Instead of YOU (the root) reading a skill
    guide into your own context and reasoning over it, you hand the stage off: this
    fetches the guide itself, ships it + only the data the stage needs into a fresh
    child agent, and returns the child's clean dict. The guide text and the child's
    working tokens NEVER enter your context — you only get the small result back.

    Use it for each planning stage in order, e.g.:
        intent = await delegate_stage("intent_extraction", "intent_extraction",
                                      {"prompt": context["original_prompt"]})
        dims   = await delegate_stage("dimension_reasoning", "dimension_reasoning",
                                      {"intent": intent})
        prim   = await delegate_stage("primitive_planning", "primitive_planning",
                                      {"intent": intent, "dimensions": dims})

    Args:
        stage: short label for the stage (e.g. "intent_extraction"), for the child.
        skill_name: the guide to fetch and hand the child (e.g. "primitive_planning").
        payload: ONLY the data this stage needs (prior stage results, the prompt).
                 Keep it minimal — do not dump your whole context in.

    Returns:
        The child's result as a Python dict (e.g. {"steps": [...]} for
        primitive_planning, or extracted fields for intent_extraction).
    """
    import os

    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    guide = requests.get(
        f"{base}/internal/read-skill",
        params={"name": skill_name},
        timeout=10,
    ).text

    _llm_query = globals()["llm_query"]
    g = globals()
    child_tools = [
        g[name] for name in ("lookup_primitive", "lookup_design_reference") if name in g
    ]

    child_context = {
        "task": (
            f"You are the '{stage}' stage of a CAD planner. Follow the GUIDE exactly "
            "and operate ONLY on the PAYLOAD given. Use lookup_primitive(key) for exact "
            "parameter names when the guide calls for it. Return a single JSON object "
            "with this stage's result — no prose, no explanation."
        ),
        "guide": guide,
        "payload": payload,
    }
    return await _llm_query(child_context, {"type": "object"}, tools=child_tools)

