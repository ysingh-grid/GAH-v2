"""Cached Temporal client factory.

Call `get_client()` once; subsequent calls return the same connected client.
The connection is process-level — do not share across asyncio event loops.
"""

from __future__ import annotations

import os

from temporalio.client import Client

_TEMPORAL_HOST      = os.environ.get("TEMPORAL_HOST", "localhost:7233")
_TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")

_client: Client | None = None


async def get_client() -> Client:
    """Return (or create) the shared Temporal client."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = await Client.connect(
            _TEMPORAL_HOST,
            namespace=_TEMPORAL_NAMESPACE,
        )
    return _client
