from typing import Any
from .artifacts import run_dir, _REPO_ROOT

def load_trace(run_id: str) -> dict[str, Any]:
    """
    Reads a stored trace artifact from disk for the given run_id.

    This tool is used by the Root RLM to inspect past runs,
    and is exposed by the FastAPI GET /designs/:id/trace endpoint.

    Args:
        run_id: The unique identifier of the run whose trace should be loaded.

    Returns:
        dict[str, Any]: A dictionary containing:
        - success: bool
        - trace: dict (the full trace payload, if success=True)
        - error: str (optional, if success=False)
    """
    import json

    trace_path = run_dir(run_id) / "trace.json"

    if not trace_path.exists():
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
        list[str]: A list of run_id strings.
    """
    import os

    artifacts_dir = _REPO_ROOT / "artifacts"

    if not artifacts_dir.exists():
        return []

    # A run = any artifacts/{run_id}/ folder that contains a trace.json
    return sorted(
        [
            d
            for d in os.listdir(artifacts_dir)
            if (artifacts_dir / d).is_dir()
            and (artifacts_dir / d / "trace.json").exists()
        ]
    )

