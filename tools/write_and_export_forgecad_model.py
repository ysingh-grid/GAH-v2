import re
from pathlib import Path
from typing import Any

try:
    from .export_forgecad_to_stl import export_forgecad_to_stl
    from .write_workspace_file import write_workspace_file
except ImportError:
    from export_forgecad_to_stl import export_forgecad_to_stl
    from write_workspace_file import write_workspace_file


DESIGN_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def write_and_export_forgecad_model(design_name: str, js_content: str) -> dict[str, Any]:
    """Write outputs/<design_name>/model.forge.js and export it to STL."""
    if not DESIGN_NAME_RE.fullmatch(design_name):
        raise ValueError(
            "design_name must be kebab-case using lowercase letters, numbers, "
            "and single hyphens"
        )
    if not js_content.strip():
        raise ValueError("js_content must not be empty")

    js_path = Path("outputs") / design_name / "model.forge.js"
    stl_path = Path("outputs") / design_name / "model.stl"

    write_workspace_file(js_path.as_posix(), js_content)
    logs = export_forgecad_to_stl(js_path.as_posix(), stl_path.as_posix())

    return {
        "design_name": design_name,
        "js_file_path": js_path.as_posix(),
        "stl_file_path": stl_path.as_posix(),
        "success": True,
        "compilation_logs": logs,
    }
