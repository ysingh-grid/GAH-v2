"""Temporal service lifecycle manager.

Manages the Temporal server + worker as subprocesses so the UI toggle
button becomes a true power switch — no CLI commands needed.

The server is started once (if not already running) and the worker is
spawned/stopped on toggle. Port 7233 already in use → skip server start,
just manage the worker.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TEMPORAL_HOST = os.environ.get("TEMPORAL_HOST", "localhost:7233")
_TEMPORAL_UI_PORT = os.environ.get("TEMPORAL_UI_PORT", "8233")

# ── Globals (module-level, one per process — FastAPI runs single-process) ────
_server_proc: subprocess.Popen | None = None
_worker_proc: subprocess.Popen | None = None


def _temporal_bin() -> str:
    """Return the path to the `temporal` CLI, or raise if not found."""
    path = shutil.which("temporal")
    if not path:
        raise RuntimeError(
            "temporal CLI not found in PATH. Install it: brew install temporal"
        )
    return path


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP port is accepting connections."""
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False


def start_server() -> bool:
    """Start the Temporal dev server if not already running.

    Returns True if the server is running after this call (either started
    now or was already up).
    """
    global _server_proc

    host, _, port_str = _TEMPORAL_HOST.partition(":") if ":" in _TEMPORAL_HOST else ("localhost", ":", _TEMPORAL_HOST)
    if not port_str:
        port_str = "7233"
    port = int(port_str)
    if not host:
        host = "localhost"

    if _port_open(host, port):
        log.info("Temporal server already running on %s:%d", host, port)
        return True

    bin_path = _temporal_bin()
    cmd = [
        bin_path, "server", "start-dev",
        "--ip", "0.0.0.0",
        "--ui-port", str(_TEMPORAL_UI_PORT),
    ]
    log.info("Starting Temporal dev server: %s", " ".join(cmd))
    try:
        _server_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(_REPO_ROOT),
        )
    except OSError as exc:
        log.error("Failed to start Temporal server: %s", exc)
        return False

    # Wait up to 10 s for port 7233 to open
    for _ in range(20):
        if _port_open(host, port, timeout=0.5):
            log.info("Temporal server ready on %s:%d", host, port)
            return True
        time.sleep(0.5)

    log.warning("Temporal server started but port %s:%d not open after 10 s", host, port)
    return False


def start_worker() -> bool:
    """Start the Temporal worker as a subprocess.

    Spawns `uv run python -m temporal.worker` which polls the 'design'
    task queue. Returns True if the worker started successfully.
    """
    global _worker_proc

    if _worker_proc is not None and _worker_proc.poll() is None:
        log.info("Temporal worker already running (pid %d)", _worker_proc.pid)
        return True

    cmd = [sys.executable, "-m", "temporal.worker"]
    log.info("Starting Temporal worker: %s", " ".join(cmd))
    try:
        _worker_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(_REPO_ROOT),
            text=True,
        )
    except OSError as exc:
        log.error("Failed to start Temporal worker: %s", exc)
        return False

    # Give it a moment to init, then check it's still alive
    time.sleep(2)
    if _worker_proc.poll() is not None:
        # Worker exited immediately — read its output for diagnostics
        if _worker_proc.stdout:
            output = _worker_proc.stdout.read()
            log.error("Worker exited immediately. Output:\n%s", output)
        _worker_proc = None
        return False

    log.info("Temporal worker started (pid %d)", _worker_proc.pid)
    return True


def stop_worker() -> bool:
    """Stop the Temporal worker subprocess if running."""
    global _worker_proc

    if _worker_proc is None:
        return True
    if _worker_proc.poll() is not None:
        _worker_proc = None
        return True

    log.info("Stopping Temporal worker (pid %d)", _worker_proc.pid)
    _worker_proc.terminate()
    try:
        _worker_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _worker_proc.kill()
    _worker_proc = None
    return True


def status() -> dict:
    """Return current Temporal services status."""
    host, _, port_str = _TEMPORAL_HOST.partition(":") if ":" in _TEMPORAL_HOST else ("localhost", ":", _TEMPORAL_HOST)
    if not port_str:
        port_str = "7233"
    port = int(port_str)
    if not host:
        host = "localhost"

    server_up = _port_open(host, port)
    worker_up = _worker_proc is not None and _worker_proc.poll() is None

    return {
        "server_up": server_up,
        "worker_up": worker_up,
        "temporal_host": f"{host}:{port}",
        "ui_port": _TEMPORAL_UI_PORT,
    }


def ensure_running() -> dict:
    """Idempotent: make sure server + worker are both up.

    Call this when the user toggles Temporal ON. If the server is already
    running (port in use), it skips the server start and only starts the
    worker.
    """
    server_ok = start_server()
    worker_ok = start_worker() if server_ok else False
    return status()