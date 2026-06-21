import subprocess
import sys
import time
from typing import Any, Callable

from backend.config import settings
from backend.utils.response import BridgeError


def _completed(name: str, start: float, stdout: str = "", stderr: str = "", exit_code: int = 0) -> dict:
    return {
        "pipeline_name": name,
        "status": "completed" if exit_code == 0 else "failed",
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "duration_seconds": round(time.monotonic() - start, 4),
    }


def run_noop(args: dict[str, Any], timeout_seconds: int) -> dict:
    start = time.monotonic()
    return _completed("noop", start, stdout="noop completed")


def run_repo_check(args: dict[str, Any], timeout_seconds: int) -> dict:
    start = time.monotonic()
    required = ["skills", "pipelines", "output", "traces", "generated"]
    missing = [name for name in required if not (settings.project_root / name).exists()]
    if missing:
        return _completed("repo_check", start, stderr=f"Missing directories: {', '.join(missing)}", exit_code=1)
    return _completed("repo_check", start, stdout="Required bridge directories exist")


def run_python_tests(args: dict[str, Any], timeout_seconds: int) -> dict:
    start = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest"],
            cwd=settings.project_root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BridgeError("PIPELINE_TIMEOUT", f"python_tests timed out after {timeout_seconds} seconds") from exc
    return _completed("python_tests", start, result.stdout, result.stderr, result.returncode)


def run_placeholder(name: str) -> Callable[[dict[str, Any], int], dict]:
    def _run(args: dict[str, Any], timeout_seconds: int) -> dict:
        start = time.monotonic()
        return _completed(name, start, stdout=f"{name} placeholder completed")

    return _run


PIPELINES: dict[str, Callable[[dict[str, Any], int], dict]] = {
    "noop": run_noop,
    "repo_check": run_repo_check,
    "python_tests": run_python_tests,
    "cad_generation": run_placeholder("cad_generation"),
    "mesh_inspection": run_placeholder("mesh_inspection"),
}


def run_pipeline(pipeline_name: str, args: dict[str, Any], timeout_seconds: int) -> dict:
    pipeline = PIPELINES.get(pipeline_name)
    if pipeline is None:
        raise BridgeError("UNKNOWN_PIPELINE", f"Unknown pipeline: {pipeline_name}")
    timeout = min(max(1, timeout_seconds), settings.command_timeout_seconds)
    result = pipeline(args, timeout)
    if result.get("exit_code", 0) != 0:
        raise BridgeError("PIPELINE_FAILED", result.get("stderr") or f"Pipeline failed: {pipeline_name}")
    return result
