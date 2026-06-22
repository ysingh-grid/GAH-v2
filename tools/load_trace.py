def load_trace(run_id: str) -> dict:
    """
    Reads a stored trace artifact from disk for the given run_id.

    This tool is used by the Root RLM to inspect past runs,
    and is exposed by the FastAPI GET /designs/:id/trace endpoint.

    Args:
        run_id: The unique identifier of the run whose trace should be loaded.

    Returns:
        A dictionary containing:
        - success: bool
        - trace: dict (the full trace payload, if success=True)
        - error: str (optional, if success=False)
    """
    import json
    import os

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    trace_path = os.path.join(base_dir, "outputs", run_id, "trace.json")

    if not os.path.exists(trace_path):
        return {
            "success": False,
            "error": f"No trace found for run_id '{run_id}' at path: {trace_path}",
        }

    try:
        with open(trace_path, encoding="utf-8") as f:
            trace = json.load(f)
        return {"success": True, "trace": trace}
    except Exception as e:
        import traceback

        return {
            "success": False,
            "error": f"Failed to load trace: {str(e)}",
            "traceback": traceback.format_exc(),
        }


def list_traces() -> list[str]:
    """
    Lists all available run_ids that have a saved trace artifact.

    Returns:
        A list of run_id strings.
    """
    import os

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outputs_dir = os.path.join(base_dir, "outputs")

    if not os.path.exists(outputs_dir):
        return []

    # A run = any outputs/{run_id}/ folder that contains a trace.json
    return sorted(
        [
            d
            for d in os.listdir(outputs_dir)
            if os.path.isdir(os.path.join(outputs_dir, d))
            and os.path.exists(os.path.join(outputs_dir, d, "trace.json"))
        ]
    )
