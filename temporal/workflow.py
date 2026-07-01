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
        compile_activity,
        execute_activity,
        inspect_activity,
        record_trace_activity,
        render_activity,
        repair_activity,
        replan_activity,
        verify_activity,
    )
    from temporal.shared import (
        CompileInput,
        DesignInput,
        DesignResult,
        DesignStage,
        ExecuteInput,
        InspectInput,
        RenderInput,
        RepairInput,
        ReplanInput,
        TraceInput,
        VerifyInput,
    )

# Per-step timeouts. The old monolithic generate is now five activities; each is
# small except execute (CadQuery/OCCT) and render (VTK). verify is one Gemini
# multimodal call; replan is one full-tool Gemini turn.
_COMPILE_TIMEOUT = timedelta(minutes=1)
_EXECUTE_TIMEOUT = timedelta(minutes=6)
_INSPECT_TIMEOUT = timedelta(minutes=2)
_REPAIR_TIMEOUT = timedelta(minutes=3)
_RENDER_TIMEOUT = timedelta(minutes=2)
_VERIFY_TIMEOUT = timedelta(minutes=3)
# Effectively uncapped: the 3min budget killed replans mid-flight even after a
# valid plan was produced (subprocess.communicate() got CancelledError while the
# underlying fast-rlm process had already finished). replan_activity now runs the
# scoped, no-fork run_replanner_turn (runtime/planner.py) which is bounded by
# design (single-block FINAL, no delegate_features) — the outer cap here is a
# safety ceiling, not the real constraint.
_REPLAN_TIMEOUT = timedelta(hours=1)
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
        inner = 0                       # compile/execute/mesh attempts (cap 5)
        outer = 0                       # visual_mismatch attempts (cap 2)

        while True:
            # ── GENERATE (split into per-step activities) ──────────────────────
            # compile → execute → inspect → (repair?) → render. Each is its own
            # Temporal activity → a distinct timeline event, repeated every loop.
            # The STL flows between steps by file path on the shared ./outputs volume.
            code = ""
            execution_result: dict = {}
            mesh_report: dict = {}
            renders: dict = {}
            stl_path = ""
            failure_stage = ""
            failure_detail = ""

            self._stage = DesignStage.GENERATING
            comp = await workflow.execute_activity(
                compile_activity,
                CompileInput(plan_dict=plan_dict, run_id=inp.run_id),
                schedule_to_close_timeout=_COMPILE_TIMEOUT,
                retry_policy=_NO_RETRY,
            )
            code = comp.code
            if not comp.ok:
                failure_stage, failure_detail = comp.failure_stage, comp.failure_detail

            if not failure_stage:
                ex = await workflow.execute_activity(
                    execute_activity,
                    ExecuteInput(code=code, run_id=inp.run_id),
                    schedule_to_close_timeout=_EXECUTE_TIMEOUT,
                    retry_policy=_NO_RETRY,
                )
                execution_result = ex.execution_result
                stl_path = ex.stl_path
                if not ex.ok:
                    failure_stage, failure_detail = ex.failure_stage, ex.failure_detail

            if not failure_stage:
                self._stage = DesignStage.INSPECTING
                insp = await workflow.execute_activity(
                    inspect_activity,
                    InspectInput(stl_path=stl_path),
                    schedule_to_close_timeout=_INSPECT_TIMEOUT,
                    retry_policy=_NO_RETRY,
                )
                mesh_report = insp.mesh_report
                if not insp.passes:
                    # Only repair when inspect failed (mirrors the in-process loop).
                    self._stage = DesignStage.REPAIRING
                    rep_mesh = await workflow.execute_activity(
                        repair_activity,
                        RepairInput(stl_path=stl_path, run_id=inp.run_id),
                        schedule_to_close_timeout=_REPAIR_TIMEOUT,
                        retry_policy=_NO_RETRY,
                    )
                    if rep_mesh.mesh_report:
                        mesh_report = rep_mesh.mesh_report
                    if not rep_mesh.passes:
                        failure_stage, failure_detail = rep_mesh.failure_stage, rep_mesh.failure_detail
                    else:
                        stl_path = rep_mesh.repaired_stl_path

            if not failure_stage:
                self._stage = DesignStage.GENERATING
                rnd = await workflow.execute_activity(
                    render_activity,
                    RenderInput(stl_path=stl_path, run_id=inp.run_id),
                    schedule_to_close_timeout=_RENDER_TIMEOUT,
                    retry_policy=_NO_RETRY,
                )
                renders = rnd.renders
                if not rnd.ok:
                    failure_stage, failure_detail = rnd.failure_stage, rnd.failure_detail

            geometry_ok = not failure_stage
            verdict: dict = {}

            # ── VERIFY ────────────────────────────────────────────────────────
            # Only runs if geometry was produced. A reject becomes a visual_mismatch.
            if geometry_ok:
                self._stage = DesignStage.VERIFYING
                ver = await workflow.execute_activity(
                    verify_activity,
                    VerifyInput(
                        prompt=inp.original_prompt,
                        code=code,
                        execution_result=execution_result,
                        mesh_report=mesh_report,
                        renders=renders,
                        prior_feedback=list(feedback_log),
                    ),
                    schedule_to_close_timeout=_VERIFY_TIMEOUT,
                    retry_policy=_NO_RETRY,
                )
                verdict = ver.verdict
                if not ver.passed:
                    failure_stage = str(verdict.get("failure_stage") or "visual_mismatch")
                    failure_detail = ver.feedback
                    feedback_log.append(ver.feedback)

            # ── SUCCESS ───────────────────────────────────────────────────────
            if not failure_stage:
                self._stage = DesignStage.DONE
                await self._record(inp, plan_dict, code, execution_result, mesh_report,
                                   renders, verdict, status="success", attempts=inner + outer + 1)
                return DesignResult(
                    status="success",
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
                await self._record(inp, plan_dict, code, execution_result, mesh_report,
                                   renders, verdict, status="failed", attempts=inner + outer,
                                   failure_stage=failure_stage, failure_detail=failure_detail)
                return DesignResult(
                    status="failed",
                    final_plan=plan_dict,
                    run_id=inp.run_id,
                    failure_category=category_for_stage(failure_stage).value,
                    message=f"exhausted attempts at stage '{failure_stage}'",
                )

            # ── REPLAN ────────────────────────────────────────────────────────
            # Scoped replanner fixes the plan from the failure message. It always
            # attempts a fix — no ask_user escalation; rep.ok=False means it
            # genuinely couldn't (exception/exhaustion), which we tag "failed".
            # Distinct REPLANNING stage (not PLANNING) so the chat UI shows the loop-back.
            self._stage = DesignStage.REPLANNING
            rep = await workflow.execute_activity(
                replan_activity,
                ReplanInput(
                    original_prompt=inp.original_prompt,
                    last_plan_dict=plan_dict,
                    failure_stage=failure_stage,
                    detail=failure_detail,
                    backend_url=inp.backend_url,
                ),
                schedule_to_close_timeout=_REPLAN_TIMEOUT,
                retry_policy=_NO_RETRY,
            )
            if not rep.ok:
                self._stage = DesignStage.FAILED
                await self._record(inp, plan_dict, code, execution_result, mesh_report,
                                   renders, verdict, status="failed", attempts=inner + outer,
                                   failure_stage="replan_error", failure_detail=rep.error)
                return DesignResult(
                    status="failed",
                    final_plan=plan_dict,
                    run_id=inp.run_id,
                    failure_category=category_for_stage("replan_error").value,
                    message=rep.error or "replanner failed to produce a corrected plan",
                )
            plan_dict = rep.plan_dict  # corrected plan → next attempt

    async def _record(
        self,
        inp: DesignInput,
        plan_dict: dict,
        code: str,
        execution_result: dict,
        mesh_report: dict,
        renders: dict,
        verdict: dict,
        *,
        status: str,
        attempts: int,
        failure_stage: str = "",
        failure_detail: str = "",
    ) -> None:
        """Write the auditable trace for the final outcome (artifact-store record).

        Takes the per-step artifacts directly (the split GENERATE no longer returns
        a single GenerateOutput).
        """
        await workflow.execute_activity(
            record_trace_activity,
            TraceInput(
                run_id=inp.run_id,
                prompt=inp.original_prompt,
                plan_dict=plan_dict,
                code=code,
                execution_result=execution_result,
                mesh_report=mesh_report,
                renders=renders,
                verdict=verdict,
                status=status,
                attempts=attempts,
                failure_stage=failure_stage,
                failure_detail=failure_detail,
            ),
            schedule_to_close_timeout=_TRACE_TIMEOUT,
            retry_policy=_NO_RETRY,
        )
