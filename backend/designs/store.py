"""In-memory session store for the designs service.

Thread-safe: all mutations go through a lock so concurrent WebSocket handlers
can't corrupt sessions. Temporal (M11) will replace this with a durable store;
for now the dict survives until the process restarts.
"""

from __future__ import annotations

import threading

from backend.designs.models import DesignSession, new_session

_lock = threading.Lock()
_sessions: dict[str, DesignSession] = {}


def create_session() -> DesignSession:
    """Create and register a new DesignSession. Returns the new session."""
    with _lock:
        session = new_session()
        _sessions[session.id] = session
        return session


def get_session(session_id: str) -> DesignSession:
    """Return the session for *session_id*.

    Raises:
        KeyError: session not found.
    """
    with _lock:
        if session_id not in _sessions:
            raise KeyError(f"design session not found: {session_id!r}")
        return _sessions[session_id]


def _clear_for_testing() -> None:
    with _lock:
        _sessions.clear()
