import json

from backend.security.path_guard import ensure_read_allowed, relative_path
from backend.utils.response import BridgeError


def inspect_output(path: str, inspection_type: str) -> dict:
    resolved = ensure_read_allowed(path)
    rel = relative_path(resolved)
    if inspection_type == "file_metadata":
        return {
            "path": rel,
            "exists": resolved.exists(),
            "type": "directory" if resolved.is_dir() else "file" if resolved.is_file() else "missing",
            "size_bytes": resolved.stat().st_size if resolved.exists() and resolved.is_file() else None,
            "extension": resolved.suffix,
        }
    if not resolved.exists() or not resolved.is_file():
        raise BridgeError("FILE_NOT_FOUND", f"Output file not found: {path}")
    if inspection_type == "json_summary":
        with resolved.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        summary = {"json_type": type(payload).__name__}
        if isinstance(payload, dict):
            summary["top_level_keys"] = sorted(payload.keys())
        elif isinstance(payload, list):
            summary["length"] = len(payload)
        return {"path": rel, "summary": summary}
    if inspection_type == "pipeline_report":
        with resolved.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return {"path": rel, "summary": {"status": payload.get("status"), "errors": payload.get("errors", [])}}
    if inspection_type == "mesh_summary":
        return {"path": rel, "summary": {"status": "unsupported", "message": "Mesh summary is not implemented in this bridge."}}
    raise BridgeError("INSPECTION_FAILED", f"Unknown inspection type: {inspection_type}")
