"""GAH Temporal worker — polls the 'design' task queue and executes activities.

Run directly:
    uv run python -m temporal.worker

Or via docker compose:
    docker compose up worker
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import logging
import os

from temporalio.worker import Worker

from temporal import activities as _activities_module
from temporal.client import get_client
from temporal.workflow import DesignWorkflow

_TASK_QUEUE = os.environ.get("TEMPORAL_TASK_QUEUE", "design")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _discover_activities() -> list:
    """Every @activity.defn function in temporal.activities, auto-registered.

    A manually maintained list here silently drops a NEW activity the moment
    someone adds one to activities.py without updating this file too — exactly
    what happened when edit_activity shipped without a matching entry here: the
    workflow scheduled it, the worker rejected it with "Activity function ...
    is not registered", and every edit hard-failed. @activity.defn stamps a
    `__temporal_activity_definition` attribute on the function (confirmed via
    the SDK's own decorator); collecting every module-level function with that
    attribute makes a repeat of this bug structurally impossible.
    """
    return [
        obj
        for _, obj in inspect.getmembers(_activities_module, inspect.isfunction)
        if hasattr(obj, "__temporal_activity_definition")
    ]


async def main() -> None:
    client = await get_client()
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as activity_executor:
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[DesignWorkflow],
            activities=_discover_activities(),
            activity_executor=activity_executor,
        ):
            log.info(
                "Worker running on task queue '%s' (BACKEND_URL=%r). Ctrl-C to stop.",
                _TASK_QUEUE,
                os.environ.get("BACKEND_URL", ""),
            )
            await asyncio.Future()  # run forever until cancelled


if __name__ == "__main__":
    asyncio.run(main())
