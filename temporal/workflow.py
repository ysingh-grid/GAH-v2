"""DesignWorkflow — Temporal workflow that runs the geometry pipeline.

Orchestrates two activities:
  1. run_geometry_activity — CadQuery compile + MeshLib verify + replan loop
  2. compile_forge_activity — deterministic plan → .forge.js

The workflow is intentionally thin: no business logic lives here, only
activity calls, timeouts, and retry configuration.  Business logic belongs
in runtime/ where it is Temporal-free and unit-testable.

Temporal constraints inside @workflow.defn:
  - No I/O, no random, no datetime.now() — use workflow.now() instead.
  - Runtime imports that touch real code go inside `with workflow.unsafe.imports_passed_through()`.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from temporal.activities import compile_forge_activity, run_geometry_activity
    from temporal.shared import DesignInput, DesignResult

_GEO_TIMEOUT   = timedelta(minutes=10)
_FORGE_TIMEOUT = timedelta(minutes=2)

# No auto-retries — the geometry loop already retries internally (up to 5
# outer attempts via replan.py).  Letting Temporal retry on top would double
# the attempts and burn extra Gemini quota.
_NO_RETRY = RetryPolicy(maximum_attempts=1)
_FORGE_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=5))


@workflow.defn
class DesignWorkflow:
    """Durable geometry pipeline for a single design request."""

    @workflow.run
    async def run(self, inp: DesignInput) -> DesignResult:
        # ── Activity 1: geometry loop ─────────────────────────────────────────
        geo: DesignResult = await workflow.execute_activity(
            run_geometry_activity,
            inp,
            schedule_to_close_timeout=_GEO_TIMEOUT,
            retry_policy=_NO_RETRY,
        )

        if geo.status != "success":
            # needs_user or failed — return as-is; caller streams the event.
            return geo

        # ── Activity 2: compile plan → .forge.js ─────────────────────────────
        forge_js: str = await workflow.execute_activity(
            compile_forge_activity,
            inp,
            schedule_to_close_timeout=_FORGE_TIMEOUT,
            retry_policy=_FORGE_RETRY,
        )

        return DesignResult(
            status="success",
            forge_js=forge_js,
            final_plan=geo.final_plan,
            run_id=geo.run_id,
        )
