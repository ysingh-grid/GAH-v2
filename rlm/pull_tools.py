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


def web_search(query: str) -> dict:
    """Search the web for a real-world measurement or standard.

    Use during the chat to look up values the user may not know (e.g. standard
    DIN-rail width, an M5 clearance hole, a typical wall thickness) and then
    ALWAYS offer the user concrete options to choose from. Returns
    {"query", "answer", "sources": [{"title", "uri"}]}; an "error" key (and
    empty answer) means the lookup found nothing — treat that as "ask the user".
    """
    import os

    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    resp = requests.get(f"{base}/internal/web-search", params={"q": query}, timeout=30)
    resp.raise_for_status()
    return resp.json()
