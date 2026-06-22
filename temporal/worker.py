"""GAH Temporal worker — polls the 'design' task queue and executes activities.

Run directly:
    uv run python -m temporal.worker

Or via docker compose:
    docker compose up worker
"""

from __future__ import annotations

import asyncio
import logging
import os

from temporalio.worker import Worker

from temporal.activities import (
    generate_activity,
    record_trace_activity,
    replan_activity,
    verify_activity,
)
from temporal.client import get_client
from temporal.workflow import DesignWorkflow

_TASK_QUEUE = os.environ.get("TEMPORAL_TASK_QUEUE", "design")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


import concurrent.futures

async def main() -> None:
    client = await get_client()
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as activity_executor:
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[DesignWorkflow],
            activities=[
                generate_activity,
                verify_activity,
                replan_activity,
                record_trace_activity,
            ],
            activity_executor=activity_executor,
        ):
            log.info("Worker running on task queue '%s'. Ctrl-C to stop.", _TASK_QUEUE)
            await asyncio.Future()  # run forever until cancelled


if __name__ == "__main__":
    asyncio.run(main())
