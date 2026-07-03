import atexit
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

# Paths
ROOT = Path(__file__).resolve().parent.parent.parent
LOGS = ROOT / "logs"

# State
_TPROCS = {"server": None, "worker": None}
_TLOCK = threading.Lock()
_LAST_WORKER_STARTED_AT: str | None = None
log = logging.getLogger(__name__)


def _temporal_cli_installed() -> bool:
    return _temporal_cli_path() is not None


def _temporal_cli_path() -> str | None:
    return shutil.which("temporal")


def _temporal_reachable() -> bool:
    """Fast, fail-open TCP probe of the Temporal server (default localhost:7233)."""
    addr = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    try:
        host, _, port = addr.partition(":")
        with socket.create_connection((host or "localhost", int(port or "7233")), timeout=0.25):
            return True
    except Exception:
        return False


def _worker_alive() -> bool:
    p = _TPROCS.get("worker")
    return p is not None and p.poll() is None


def _server_proc_alive() -> bool:
    p = _TPROCS.get("server")
    return p is not None and p.poll() is None


def status() -> dict:
    worker = _TPROCS.get("worker")
    managed_worker_up = _worker_alive()
    worker_exit_code = None if worker is None else worker.poll()
    return {
        "cli": _temporal_cli_installed(),
        "server_up": _temporal_reachable(),
        "managed_worker_up": managed_worker_up,
        "worker_up": managed_worker_up,
        "worker_exit_code": worker_exit_code,
        "last_worker_started_at": _LAST_WORKER_STARTED_AT,
        "last_worker_errors": _last_error_lines(LOGS / "temporal_worker.log", limit=20),
    }


def ensure_running() -> tuple[bool, str]:
    """Bring up the dev server + worker as managed subprocesses."""
    global _LAST_WORKER_STARTED_AT  # noqa: PLW0603
    with _TLOCK:
        if not _temporal_cli_installed():
            return (False, "Temporal CLI not installed. Run `brew install temporal`.")
        temporal_bin = _temporal_cli_path()
        if temporal_bin is None:
            return (False, "Temporal CLI not installed. Run `brew install temporal`.")
        
        try:
            LOGS.mkdir(exist_ok=True)
            
            # Start Server
            if not _temporal_reachable() and not _server_proc_alive():
                slog = open(LOGS / "temporal_server.log", "ab")
                _TPROCS["server"] = subprocess.Popen(  # noqa: S603
                    [temporal_bin, "server", "start-dev"],
                    cwd=str(ROOT),
                    stdout=slog,
                    stderr=slog,
                )
                for _ in range(24):  # up to ~12s
                    if _temporal_reachable():
                        break
                    time.sleep(0.5)
                if not _temporal_reachable():
                    return (False, "Temporal server did not come up. Check logs.")
            
            # Start Worker
            if not _worker_alive():
                wlog = open(LOGS / "temporal_worker.log", "ab")
                env = {**os.environ, "PYTHONPATH": str(ROOT)}
                _TPROCS["worker"] = subprocess.Popen(
                    [sys.executable, "-m", "temporal.worker"], cwd=str(ROOT),
                    env=env, stdout=wlog, stderr=wlog
                )
                _LAST_WORKER_STARTED_AT = datetime.now(UTC).isoformat()
                time.sleep(2.0)
                if _TPROCS["worker"].poll() is not None:
                    return (False, "Worker exited immediately. Check logs.")
            
            return (True, "Temporal is up (server + worker).")
        except Exception as e:
            return (False, f"could not start Temporal: {type(e).__name__}: {e}")


def stop_worker() -> None:
    """Terminate the worker and the server."""
    global _LAST_WORKER_STARTED_AT  # noqa: PLW0603
    with _TLOCK:
        for key in ("worker", "server"):
            p = _TPROCS.get(key)
            if p is not None and p.poll() is None:
                try:
                    p.terminate()
                    p.wait(timeout=5)
                except Exception:
                    try:
                        p.kill()
                    except Exception as exc:
                        log.warning("could not kill Temporal %s process: %s", key, exc)
            _TPROCS[key] = None
        _LAST_WORKER_STARTED_AT = None


def _last_error_lines(path: Path, *, limit: int) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    errors = [
        line
        for line in lines
        if "ERROR" in line or "WARNING" in line or "Traceback" in line or "TypeError" in line
    ]
    return errors[-limit:]


atexit.register(stop_worker)
