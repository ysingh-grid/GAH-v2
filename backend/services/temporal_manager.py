import atexit
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

# Paths
ROOT = Path(__file__).resolve().parent.parent.parent
LOGS = ROOT / "logs"

# State
_TPROCS = {"server": None, "worker": None}
_TLOCK = threading.Lock()


def _temporal_cli_installed() -> bool:
    return shutil.which("temporal") is not None


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
    return {
        "cli": _temporal_cli_installed(),
        "server_up": _temporal_reachable(),
        "worker_up": _worker_alive(),
    }


def ensure_running() -> tuple[bool, str]:
    """Bring up the dev server + worker as managed subprocesses."""
    with _TLOCK:
        if not _temporal_cli_installed():
            return (False, "Temporal CLI not installed. Run `brew install temporal`.")
        
        try:
            LOGS.mkdir(exist_ok=True)
            
            # Start Server
            if not _temporal_reachable() and not _server_proc_alive():
                slog = open(LOGS / "temporal_server.log", "ab")
                _TPROCS["server"] = subprocess.Popen(
                    ["temporal", "server", "start-dev"], cwd=str(ROOT), stdout=slog, stderr=slog
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
                time.sleep(2.0)
                if _TPROCS["worker"].poll() is not None:
                    return (False, "Worker exited immediately. Check logs.")
            
            return (True, "Temporal is up (server + worker).")
        except Exception as e:
            return (False, f"could not start Temporal: {type(e).__name__}: {e}")


def stop_worker():
    """Terminate the worker and the server."""
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
                    except Exception:
                        pass
            _TPROCS[key] = None


atexit.register(stop_worker)
