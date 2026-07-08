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
    DTCM_BACKEND_URL is injected via fast-rlm's env_variables, not hardcoded.
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
    """Return the full spec of one primitive: params, verification, template.

    The RLM calls this once it has picked a shape and needs its real
    parameter names and constraints to fill the plan correctly.
    """
    import os

    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    url = f"{base}/internal/lookup-primitive"
    for _attempt in range(2):
        try:
            resp = requests.get(url, params={"key": key}, timeout=10)
            if resp.status_code == 404:
                # Unknown key — a MODEL mistake, not an infra failure. Never retry
                # (the answer is deterministic); surface the server's detail, which
                # names the valid keys so the model can pick a real one next step.
                try:
                    _detail = resp.json().get("detail", resp.text)
                except Exception:
                    _detail = resp.text
                raise KeyError(f"lookup_primitive({key!r}): {_detail}")
            resp.raise_for_status()
            return resp.json()
        except KeyError:
            raise
        except Exception as _e:
            if _attempt == 0:
                continue
            raise RuntimeError(
                f"lookup_primitive({key!r}): backend unreachable at {url!r} ({_e})."
            ) from None


def preview_plan(plan: dict, critique: bool = False) -> dict:
    """Preview a candidate PrimitivePlan with REAL geometry BEFORE you FINAL it.

    Compiles and builds the plan on the host and returns structured evidence:
      - compiles / executes: did it turn into valid geometry at all (+ error text)
      - watertight, num_components, disconnected(+hint): is it ONE fused solid?
        (num_components > 1 means features only touch instead of overlapping —
        the single most common complex-part defect)
      - bbox, volume_mm3: overall scale sanity
      - per_feature: each step's REAL size — {id, operation, primitive, size_mm
        [dx,dy,dz], pct_of_overall_bbox} — so you can see if a feature that should
        be prominent is actually tiny (e.g. side frames at 3% of the bbox).
    Set critique=True to ALSO render it and get a VLM per-feature verdict (slower;
    use sparingly).

    USE THIS to sanity-check a COMPLEX / multi-feature / assembly plan and fix
    mis-sized or detached features before emitting FINAL. Do NOT preview a trivial
    single-primitive plan — it just costs time.

    HARD-CAPPED: at most 2 previews per plan (DTCM_PREVIEW_BUDGET). Once the cap is
    hit the tool REFUSES further previews and returns {"budget_exhausted": True} —
    do not rely on repeated previews; FINAL with your best current plan instead.
    """
    import os

    import requests

    # Code-level cap: the sandbox globals persist across REPL turns within one run,
    # so this counter bounds previews no matter what the prompt says (prompt limits
    # alone were ignored — the model previewed 15-24x, causing runaway latency).
    g = globals()
    budget = int(os.environ.get("DTCM_PREVIEW_BUDGET", "2"))
    used = g.get("_PREVIEW_CALLS", 0)
    if used >= budget:
        return {
            "budget_exhausted": True,
            "message": (
                f"preview_plan budget exhausted ({budget} max per plan). Do NOT "
                "preview again — emit FINAL now with your best current plan."
            ),
        }
    g["_PREVIEW_CALLS"] = used + 1

    base = os.environ["DTCM_BACKEND_URL"]
    url = f"{base}/internal/preview-plan"
    resp = requests.post(url, json={"plan": plan, "critique": critique}, timeout=180)
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


def list_skills_replan() -> list[str]:
    """Return the names of every reasoning-guide skill available to the REPLANNER.

    The replanner's live catalog of guides — scoped to revising ONE existing
    plan (repair/refinement + primitive/dimension reasoning). Planner-only
    guides (full intake/decomposition/verification playbook) are deliberately
    NOT listed here. Start with read_skill('playbook_replan').
    """
    import os

    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    url = f"{base}/internal/list-skills-replan"
    for _attempt in range(2):
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as _e:
            if _attempt == 0:
                continue
            raise RuntimeError(
                f"list_skills_replan: backend unreachable at {url!r} ({_e})."
            ) from None


def read_skill(name: str) -> str:
    """Load one skill guide into REPL memory `_SKILLS[name]` (and `context['skills'][name]`).

    Note: Core skills like 'playbook' and 'primitive_planning' are already pre-loaded
    under `context['preloaded_skills']`. Do NOT call read_skill for these;
    instead, read them directly from context. Use this function only to fetch any
    other specialized skill guides if needed.
    """
    import os

    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    url = f"{base}/internal/read-skill"
    for _attempt in range(2):
        try:
            resp = requests.get(url, params={"name": name}, timeout=10)
            if resp.status_code == 404:
                # Unknown skill name — a MODEL mistake, not an infra failure. Never
                # retry; surface the server's detail (it lists the known skills) so
                # the model can pick a real name next step.
                try:
                    _detail = resp.json().get("detail", resp.text)
                except Exception:
                    _detail = resp.text
                raise KeyError(f"read_skill({name!r}): {_detail}")
            resp.raise_for_status()
            text = resp.text
            break
        except KeyError:
            raise
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
    """Fetch specific KB sections by slug keys from list_kb_index().

    Call this in Step 1 AFTER list_kb_index() — pick only the slugs that are
    relevant to the current request. Each fetched section is ≤800 chars.

    Args:
        keys: List of slug strings from list_kb_index(), e.g.
              ["3d-operations", "revolve", "sweep"].
              Mix of cadquery and forgecad slugs is fine.
              Fetch ≤5 sections to keep token cost bounded.

    Returns:
        {slug: memory_handle} pointing to stored content in `_KB[slug]`.
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
    """Look up standard dimensions + adaptable CSG recipes for a design task.

    Call this BEFORE inventing geometry or web-searching. It stores in REPL memory:
      - `_REF['fastener_dims']` (metric clearance tables)
      - `_REF['recipes']` (adaptable CSG step templates)

    Returns dict of memory pointers. Query `_REF['recipes']` or `_REF['fastener_dims']` in Python.
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
        order requested. FLATTEN them into your main `steps` array in order: the
        first body stays as-is (its 'base' is the plan's base); every later body
        also starts with a 'base', which the schema deterministically coerces to
        'union' (a union of disjoint solids is one legal multi-component compound).
        Then preview_plan the flattened assembly once (num_components should be 1 if
        the bodies are meant to touch) and FINAL.
    """
    _llm_query = globals()["llm_query"]
    _batch_query = globals()["batch_llm_query"]
    _lookup_prim = globals()["lookup_primitive"]
    _lookup_ref = globals()["lookup_design_reference"]

    step_schema = {"type": "array", "items": {"type": "object"}}
    # Children get ONLY the read tools — NOT preview_plan. preview runs real host
    # geometry; giving it to every child caused runaway latency (children burned
    # turns previewing dummy shapes). The ROOT previews the flattened assembly once.
    child_tools = [_lookup_prim, _lookup_ref]

    queries = []
    for feat in features:
        q_context = {
            "task": (
                "Build ONLY this ONE body/feature IN THE SHARED FRAME given, as a "
                "VALID standalone plan: its FIRST step is operation 'base' (this "
                "body's root solid), any extra steps are union/cut on top. Use the "
                "absolute placement + the shared_frame anchors EXACTLY — never move a "
                "shared anchor. Where this body meets another at an interface, extend "
                "it ~0.5-1mm INTO the neighbour so the assembly fuses (no floating "
                "gaps). Use lookup_primitive(key) for exact param names. Return a "
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

