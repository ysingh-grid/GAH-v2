"""Shared CadQuery subprocess runner.

WHY: `execute_cadquery` embeds a private python-finder + subprocess + JSON-parse
harness. The preview path (Task 5) needs the exact same "run a CadQuery script in
an interpreter that has cadquery, capture its JSON stdout" behaviour, so it lives
here once and both can use it. Isolating CadQuery/OCCT in a subprocess also avoids
the Cocoa/OpenGL main-thread segfault class that bites VTK in worker threads.
"""

# This module's whole job is to run a trusted, self-generated CadQuery script in a
# child interpreter and probe candidate interpreters — so the subprocess calls
# (S603) and the probe try/except pass|continue (S110/S112) are intentional here.
# ruff: noqa: S603, S110, S112

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any


def find_cadquery_python() -> str:
    """Return a python executable that can `import cadquery` (best effort)."""
    try:
        check = subprocess.run(
            [sys.executable, "-c", "import cadquery"], capture_output=True, timeout=10
        )
        if check.returncode == 0:
            return sys.executable
    except Exception:
        pass

    candidates = [
        "/opt/anaconda3/bin/python3",
        "/opt/anaconda3/bin/python",
        os.path.expanduser("~/anaconda3/bin/python3"),
        os.path.expanduser("~/miniconda3/bin/python3"),
        "/opt/homebrew/anaconda3/bin/python3",
        "/opt/homebrew/bin/python3",
        shutil.which("python3"),
        shutil.which("python"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and candidate != sys.executable:
            try:
                check = subprocess.run(
                    [candidate, "-c", "import cadquery"], capture_output=True, timeout=10
                )
                if check.returncode == 0:
                    return candidate
            except Exception:
                continue
    return sys.executable  # fallback — the subprocess will surface the ImportError


def run_cadquery_script_json(script: str, timeout: int = 45) -> dict[str, Any]:
    """Run a CadQuery script that prints a single JSON object to stdout.

    The script is fully responsible for its own success/error JSON contract; this
    only handles interpreter selection, process isolation, and parsing. On any
    infra failure (crash, empty output, unparseable) it returns
    {"success": False, "error": ...} so callers never see a raw exception.
    """
    python_exe = find_cadquery_python()
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".py", delete=False, mode="w", encoding="utf-8"
        ) as tmp:
            tmp.write(script)
            tmp_path = tmp.name

        proc = subprocess.run(
            [python_exe, tmp_path], capture_output=True, text=True, timeout=timeout
        )
        if proc.returncode != 0:
            return {
                "success": False,
                "error": (
                    f"interpreter crashed (code {proc.returncode}). "
                    f"stderr: {proc.stderr[:2000]}"
                ),
            }
        out = proc.stdout.strip()
        if not out:
            return {
                "success": False,
                "error": f"no output. stderr: {proc.stderr[:2000]}",
            }
        try:
            result: dict[str, Any] = json.loads(out)
            return result
        except json.JSONDecodeError:
            return {"success": False, "error": f"non-JSON output: {out[:800]}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"cadquery script timed out after {timeout}s"}
    except Exception as exc:  # noqa: BLE001 — infra failure becomes a structured result
        return {
            "success": False,
            "error": f"failed to run cadquery script: {exc}",
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
