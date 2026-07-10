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

    context["available_primitives"] usually already carries each primitive's
    one-line signature (parameter names/types/defaults) — enough to fill most
    plans without any lookup. Call this only when you need the FULL spec:
    per-parameter descriptions, constraints, or an unusual primitive whose
    signature alone is ambiguous.
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

    Check `context['skills']` FIRST — your primary guide (playbook /
    playbook_replan, plus fix guides on a replan) is usually pre-loaded there;
    re-fetching it wastes a REPL step. Use this tool only for ADDITIONAL guides
    the pre-load doesn't include (see list_skills for the catalog).
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


def list_design_reference_index() -> dict:
    """Menu of reusable design references as {key: one-line description}.

    This same index is usually PRE-LOADED at context["reference_index"] — read
    it from there first; call this tool only if it's missing. It is the INDEX,
    not the content — pick the keys whose descriptions match the request, then
    call fetch_design_reference([...]) to load only those. Three kinds of key:
      - standard CSG recipes (e.g. bolt_circle, mounting_plate),
      - `fastener_dims` (metric clearance / tap / counterbore tables),
      - `approved__*` — PAST DESIGNS A USER CONFIRMED CORRECT. Prefer ADAPTING a
        proven approved design (its description is the original request) over
        inventing geometry from scratch when one matches the task.

    Returns:
        {key: description}. Pull what you need with fetch_design_reference().
    """
    import os

    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    url = f"{base}/internal/design-reference/index"
    for _attempt in range(2):
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as _e:
            if _attempt == 0:
                continue
            raise RuntimeError(
                f"list_design_reference_index: backend unreachable at {url!r} ({_e})."
            ) from None


def fetch_design_reference(keys: list[str]) -> dict:
    """Fetch specific references by key from list_design_reference_index().

    Pick only the relevant keys (recipes, `fastener_dims`, or `approved__*` past
    designs). Recipes and approved designs come back with adaptable CSG `steps`
    you can copy and re-parametrise; `fastener_dims` returns dimension tables.
    Fetch a handful, not everything, to keep token cost bounded.

    Args:
        keys: List of keys from the index, e.g.
              ["bolt_circle", "fastener_dims", "approved__design_ab12_..."].

    Returns:
        {key: memory_handle} pointing to stored content in `_REF[key]`.
    """
    import os

    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    url = f"{base}/internal/design-reference/fetch"
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
                f"fetch_design_reference({keys!r}): backend unreachable at {url!r} ({_e})."
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

