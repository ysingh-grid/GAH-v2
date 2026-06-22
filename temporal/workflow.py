"""DesignWorkflow — durable, observable geometry pipeline for one design request.

The workflow OWNS the bounded repair loop (the dashed feedback arc in architecture
diagram 03.1). Each coarse stage is a separate Temporal activity, so the Temporal
UI timeline shows generate → verify → replan as distinct events. The workflow also
tracks the current coarse stage in `self._stage` and exposes it via @workflow.query,
so the backend can poll it and stream live progress to the chat UI. One vocabulary
(DesignStage), two observability surfaces.

The control flow mirrors runtime.loop.run_geometry_loop (same caps, same inner/outer
counting via runtime.replan) — that loop remains the in-process fallback; this is the
durable, decomposed version.

Temporal constraints inside @workflow.defn:
  - No I/O, no random, no datetime.now() — use workflow.now() instead.
  - Real-code imports go inside `with workflow.unsafe.imports_passed_through()`.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from runtime.replan import is_exhausted  # pure cap logic, shared with in-process loop
    from runtime.trace import category_for_stage  # pure stage -> failure-category map
    from temporal.activities import (
        generate_activity,
        record_trace_activity,
        replan_activity,
        verify_activity,
    )
    from temporal.shared import (
        DesignInput,
        DesignResult,
        DesignStage,
        GenerateInput,
        ReplanInput,
        TraceInput,
        VerifyInput,
    )

# Per-stage timeouts. generate is the heavy one (CadQuery/OCCT + render); verify
# is one Gemini multimodal call; replan is one no-tools Gemini turn.
_GEN_TIMEOUT = timedelta(minutes=8)
_VERIFY_TIMEOUT = timedelta(minutes=3)
_REPLAN_TIMEOUT = timedelta(minutes=2)
_TRACE_TIMEOUT = timedelta(seconds=30)

# No Temporal-level retries: the workflow itself is the bounded retry loop. Letting
# Temporal also retry would double attempts and burn extra Gemini quota.
_NO_RETRY = RetryPolicy(maximum_attempts=1)


@workflow.defn
class DesignWorkflow:
    """Durable geometry pipeline; advances through observable coarse stages."""

    def __init__(self) -> None:
        # Current coarse stage, polled by the backend via the current_stage query.
        self._stage: str = DesignStage.PLANNING

    @workflow.query
    def current_stage(self) -> str:
        """Return the coarse pipeline stage (DesignStage.*) the workflow is in.

        The backend polls this on a timer while awaiting the workflow result and
        streams each change to the chat UI as a progress event.
        """
        return self._stage

    @workflow.run
    async def run(self, inp: DesignInput) -> DesignResult:
        plan_dict = inp.plan_dict
        feedback_log: list[str] = []   # verifier feedback accumulated across outer attempts
        inner = 0                       # compile/execute/mesh/forge attempts (cap 5)
        outer = 0                       # visual_mismatch attempts (cap 2)

        while True:
            # ── GENERATE ──────────────────────────────────────────────────────
            # compile CadQuery + .forge.js in parallel, execute, inspect, repair, render.
            self._stage = DesignStage.GENERATING
            gen = await workflow.execute_activity(
                generate_activity,
                GenerateInput(plan_dict=plan_dict, run_id=inp.run_id),
                schedule_to_close_timeout=_GEN_TIMEOUT,
                retry_policy=_NO_RETRY,
            )

            failure_stage = "" if gen.ok else gen.failure_stage
            failure_detail = "" if gen.ok else gen.failure_detail
            verdict: dict = {}

            # ── VERIFY ────────────────────────────────────────────────────────
            # Only runs if geometry was produced. A reject becomes a visual_mismatch.
            if gen.ok:
                self._stage = DesignStage.VERIFYING
                ver = await workflow.execute_activity(
                    verify_activity,
                    VerifyInput(
                        prompt=inp.original_prompt,
                        code=gen.code,
                        execution_result=gen.execution_result,
                        mesh_report=gen.mesh_report,
                        renders=gen.renders,
                        prior_feedback=list(feedback_log),
                    ),
                    schedule_to_close_timeout=_VERIFY_TIMEOUT,
                    retry_policy=_NO_RETRY,
                )
                verdict = ver.verdict
                if not ver.passed:
                    failure_stage = "visual_mismatch"
                    failure_detail = ver.feedback
                    feedback_log.append(ver.feedback)

            # ── SUCCESS ───────────────────────────────────────────────────────
            if not failure_stage:
                self._stage = DesignStage.DONE
                await self._record(inp, plan_dict, gen, verdict,
                                   status="success", attempts=inner + outer + 1)
                return DesignResult(
                    status="success",
                    forge_js=gen.forge_js,
                    final_plan=plan_dict,
                    run_id=inp.run_id,
                )

            # ── FAILURE: count attempt against the right cap ──────────────────
            is_outer = failure_stage == "visual_mismatch"
            if is_outer:
                outer += 1
                attempt_for_stage = outer
            else:
                inner += 1
                attempt_for_stage = inner

            # ── EXHAUSTED: give up, tag the canonical failure category ────────
            if is_exhausted(failure_stage, attempt_for_stage):
                self._stage = DesignStage.FAILED
                await self._record(inp, plan_dict, gen, verdict,
                                   status="failed", attempts=inner + outer,
                                   failure_stage=failure_stage, failure_detail=failure_detail)
                return DesignResult(
                    status="failed",
                    final_plan=plan_dict,
                    run_id=inp.run_id,
                    failure_category=category_for_stage(failure_stage).value,
                    message=f"exhausted attempts at stage '{failure_stage}'",
                )

            # ── REPLAN ────────────────────────────────────────────────────────
            # No-tools replanner fixes the plan from the failure message, or asks the user.
            self._stage = DesignStage.PLANNING
            rep = await workflow.execute_activity(
                replan_activity,
                ReplanInput(
                    original_prompt=inp.original_prompt,
                    last_plan_dict=plan_dict,
                    failure_stage=failure_stage,
                    detail=failure_detail,
                ),
                schedule_to_close_timeout=_REPLAN_TIMEOUT,
                retry_policy=_NO_RETRY,
            )
            if rep.action == "ask_user":
                self._stage = DesignStage.NEEDS_USER
                await self._record(inp, plan_dict, gen, verdict,
                                   status="needs_user", attempts=inner + outer,
                                   failure_stage=failure_stage, failure_detail=failure_detail)
                return DesignResult(
                    status="needs_user",
                    final_plan=plan_dict,
                    run_id=inp.run_id,
                    question=rep.question,
                )
            plan_dict = rep.plan_dict  # corrected plan → next attempt

    async def _record(
        self,
        inp: DesignInput,
        plan_dict: dict,
        gen,  # GenerateOutput
        verdict: dict,
        *,
        status: str,
        attempts: int,
        failure_stage: str = "",
        failure_detail: str = "",
    ) -> None:
        """Write the auditable trace for the final outcome (artifact-store record)."""
        await workflow.execute_activity(
            record_trace_activity,
            TraceInput(
                run_id=inp.run_id,
                prompt=inp.original_prompt,
                plan_dict=plan_dict,
                code=gen.code,
                execution_result=gen.execution_result,
                mesh_report=gen.mesh_report,
                renders=gen.renders,
                verdict=verdict,
                status=status,
                attempts=attempts,
                failure_stage=failure_stage,
                failure_detail=failure_detail,
            ),
            schedule_to_close_timeout=_TRACE_TIMEOUT,
            retry_policy=_NO_RETRY,
        )
