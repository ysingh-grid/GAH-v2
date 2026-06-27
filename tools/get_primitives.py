def get_primitives_library() -> dict:
    """Get the library of supported 3D CAD geometric primitives, including their
    parameters, descriptions, defaults, and verification keys.

    Returns:
        A dictionary mapping primitive names to their specifications.

    Source of truth: this reads the primitive library that the orchestrator injects
    into the REPL environment as the PRIMITIVES_JSON_DATA variable (the verbatim
    contents of schemas/primitives.json). The native REPL is a pure-WASM sandbox with
    no host filesystem access, so the data is handed in via the environment rather than
    read from disk. There is intentionally NO inlined copy here — schemas/primitives.json
    is the single source of truth, shared by this tool, the host MCP tool, and the
    Pydantic schema, so they can never drift apart.
    """
    import json
    import os

    data = os.environ.get("PRIMITIVES_JSON_DATA")
    if not data:
        raise RuntimeError(
            "PRIMITIVES_JSON_DATA is not set in this environment. The orchestrator must "
            "inject the primitive library (the contents of schemas/primitives.json) via "
            "fast_rlm.run(env_variables={'PRIMITIVES_JSON_DATA': ...}) before this tool can run."
        )
    return json.loads(data)
