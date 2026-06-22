def get_primitives() -> dict:
    """Return all available primitives with their descriptions and parameters.

    Tool the RLM calls to discover what shapes it's allowed to plan with and their specifications.
    """
    import os
    import requests

    base = os.environ["DTCM_BACKEND_URL"]
    resp = requests.get(f"{base}/internal/get-primitives", timeout=10)
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
