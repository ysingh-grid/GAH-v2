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

import json
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from runtime.replan import is_exhausted  # pure cap logic, shared with in-process loop
    from runtime.trace import category_for_stage  # pure stage -> failure-category map
    from temporal.activities import (
        auto_hollow_activity,
        compile_activity,
        execute_activity,
        host_gates_activity,
        inspect_activity,
        plan_activity,
        record_trace_activity,
        render_activity,
        repair_activity,
        replan_activity,
        verify_activity,
    )
    from temporal.shared import (
        AutoHollowInput,
        CompileInput,
        DesignInput,
        DesignResult,
        DesignStage,
        ExecuteInput,
        HostGatesInput,
        InspectInput,
        PlanInput,
        RenderInput,
        RepairInput,
        ReplanInput,
        TraceInput,
        VerifyInput,
    )

# Per-step timeouts. The old monolithic generate is now five activities; each is
# small except execute (CadQuery/OCCT) and render (VTK). verify is one Gemini
# multimodal call; replan is one full-tool Gemini turn.
# Planning is the workflow's first activity now (fast-rlm turn on the worker). Generous
# schedule_to_close ceiling; the 60s heartbeat below is the real hung-planner guard.
_PLAN_TIMEOUT = timedelta(minutes=30)
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
# Long activities heartbeat every ~10s from a side thread (temporal/activities.py
# _heartbeating). If no heartbeat lands within this window, Temporal fails the
# activity immediately — a hung worker/LLM call is detected in ~1 minute instead
# of only at the schedule_to_close ceiling (up to 1h for replan). Only set on
# activities that actually heartbeat (execute/repair/render/verify/replan);
# compile/inspect/trace finish in seconds and don't need it.
_HEARTBEAT_TIMEOUT = timedelta(seconds=60)

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

        # ── PLAN (first activity when no plan was supplied) ───────────────────
        # Empty plan_dict means "plan inside the workflow" — so the workflow starts
        # the instant intake completes (no in-process pre-Temporal gap). A ready
        # plan (edit path) skips this. self._stage already defaults to PLANNING, so
        # the current_stage query shows PLANNING immediately.
        if not plan_dict:
            self._stage = DesignStage.PLANNING
            pl = await workflow.execute_activity(
                plan_activity,
                PlanInput(
                    original_prompt=inp.original_prompt,
                    history=inp.planner_history,
                    backend_url=inp.backend_url,
                ),
                schedule_to_close_timeout=_PLAN_TIMEOUT,
                heartbeat_timeout=_HEARTBEAT_TIMEOUT,
                retry_policy=_NO_RETRY,
            )
            if not pl.ok:
                self._stage = DesignStage.FAILED
                await self._record(
                    inp, {}, "", {}, {}, {}, {}, status="failed", attempts=0,
                    failure_stage="plan_error", failure_detail=pl.error,
                )
                return DesignResult(
                    status="failed",
                    run_id=inp.run_id,
                    failure_category=category_for_stage("plan_error").value,
                    message=pl.error or "planner failed to produce a plan",
                )
            plan_dict = pl.plan_dict

        feedback_log: list[str] = []    # verifier feedback accumulated across outer attempts
        # Replan state: seeded with the pre-planner intake facts (inp.history),
        # then each round appends its failed plan + failure — full plan lineage.
        replan_history: list[dict] = list(inp.history)
        inner = 0                       # compile/execute/mesh attempts (cap 5)
        outer = 0                       # visual_mismatch attempts (cap 2)
        # Set when a replan returns the plan UNCHANGED after a verify-stage failure
        # (e.g. verifier_error): the geometry artifacts from the previous round are
        # still valid, so skip compile→execute→inspect→render and go straight to
        # re-verify instead of re-paying up to ~10min of identical recompute.
        reuse_geometry = False
        code = ""
        execution_result: dict = {}
        mesh_report: dict = {}
        renders: dict = {}
        stl_path = ""

        while True:
            # ── GENERATE (split into per-step activities) ──────────────────────
            # compile → execute → inspect → (repair?) → render. Each is its own
            # Temporal activity → a distinct timeline event, repeated every loop.
            # The STL flows between steps by file path on the shared ./outputs volume.
            failure_stage = ""
            failure_detail = ""

            if reuse_geometry:
                # Plan came back unchanged after a verify-stage failure — the
                # artifacts (code/execution_result/mesh_report/renders/stl_path)
                # from the previous round are still valid. Skip straight to verify.
                reuse_geometry = False
            else:
                code = ""
                execution_result = {}
                mesh_report = {}
                renders = {}
                stl_path = ""

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
                        heartbeat_timeout=_HEARTBEAT_TIMEOUT,
                        retry_policy=_NO_RETRY,
                    )
                    execution_result = ex.execution_result
                    stl_path = ex.stl_path
                    if not ex.ok:
                        failure_stage, failure_detail = ex.failure_stage, ex.failure_detail

                # Host auto-hollow (same helper as runtime.loop) — MUST run on the
                # Temporal path. Without this, solid-only loft adapters succeed with
                # VLM silhouette pass and never get a through cavity.
                if not failure_stage:
                    ah = await workflow.execute_activity(
                        auto_hollow_activity,
                        AutoHollowInput(
                            plan_dict=plan_dict,
                            run_id=inp.run_id,
                            prompt=inp.original_prompt,
                            feature_checklist=inp.feature_checklist,
                            through_path=inp.through_path or "",
                            execution_result=execution_result,
                            code=code,
                        ),
                        schedule_to_close_timeout=_EXECUTE_TIMEOUT,
                        heartbeat_timeout=_HEARTBEAT_TIMEOUT,
                        retry_policy=_NO_RETRY,
                    )
                    plan_dict = ah.plan_dict or plan_dict
                    if ah.code:
                        code = ah.code
                    if ah.execution_result:
                        execution_result = ah.execution_result
                    if ah.stl_path:
                        stl_path = ah.stl_path
                    if not ah.ok:
                        failure_stage, failure_detail = (
                            ah.failure_stage,
                            ah.failure_detail,
                        )

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
                            RepairInput(
                                stl_path=stl_path, run_id=inp.run_id, plan_dict=plan_dict
                            ),
                            schedule_to_close_timeout=_REPAIR_TIMEOUT,
                            heartbeat_timeout=_HEARTBEAT_TIMEOUT,
                            retry_policy=_NO_RETRY,
                        )
                        if rep_mesh.mesh_report:
                            mesh_report = rep_mesh.mesh_report
                        if not rep_mesh.passes:
                            failure_stage = rep_mesh.failure_stage
                            failure_detail = rep_mesh.failure_detail
                        else:
                            stl_path = rep_mesh.repaired_stl_path

                if not failure_stage:
                    self._stage = DesignStage.GENERATING
                    rnd = await workflow.execute_activity(
                        render_activity,
                        RenderInput(stl_path=stl_path, run_id=inp.run_id),
                        schedule_to_close_timeout=_RENDER_TIMEOUT,
                        heartbeat_timeout=_HEARTBEAT_TIMEOUT,
                        retry_policy=_NO_RETRY,
                    )
                    renders = rnd.renders
                    if not rnd.ok:
                        failure_stage, failure_detail = rnd.failure_stage, rnd.failure_detail

            geometry_ok = not failure_stage
            verdict: dict = {}

            # Host dims/hollow gates BEFORE VLM — measurable facts only.
            # Prevents solid-fill "success" when through-path is required.
            if geometry_ok:
                gates = await workflow.execute_activity(
                    host_gates_activity,
                    HostGatesInput(
                        prompt=inp.original_prompt,
                        plan_dict=plan_dict,
                        execution_result=execution_result,
                        feature_checklist=inp.feature_checklist,
                        through_path=inp.through_path or "",
                    ),
                    schedule_to_close_timeout=_COMPILE_TIMEOUT,
                    retry_policy=_NO_RETRY,
                )
                if not gates.ok:
                    failure_stage = gates.failure_stage
                    failure_detail = gates.failure_detail
                    geometry_ok = False

            # ── VERIFY ────────────────────────────────────────────────────────
            # Only runs if geometry was produced. A reject becomes a visual_mismatch.
            if geometry_ok:
                self._stage = DesignStage.VERIFYING
                ver = await workflow.execute_activity(
                    verify_activity,
                    VerifyInput(
                        prompt=inp.original_prompt,
                        execution_result=execution_result,
                        mesh_report=mesh_report,
                        renders=renders,
                        prior_feedback=list(feedback_log),
                        feature_checklist=inp.feature_checklist,
                    ),
                    schedule_to_close_timeout=_VERIFY_TIMEOUT,
                    heartbeat_timeout=_HEARTBEAT_TIMEOUT,
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
                    history=list(replan_history),
                    backend_url=inp.backend_url,
                ),
                schedule_to_close_timeout=_REPLAN_TIMEOUT,
                heartbeat_timeout=_HEARTBEAT_TIMEOUT,
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
            # Maintain STATE across plan->replan rounds (mirrors runtime/loop.py):
            # append the plan that failed AND the failure it hit, so the NEXT
            # replan sees the full plan lineage on top of the intake-facts base.
            # Bounded by the caps (<=8 rounds); the current round's plan rides in
            # the feedback message, entering history only when the next round
            # begins — no duplication within one request.
            attempt_no = inner + outer
            replan_history.append({
                "role": "planner",
                "content": f"[attempt {attempt_no} plan] "
                           + json.dumps(plan_dict, separators=(",", ":")),
            })
            replan_history.append({
                "role": "system",
                "content": (
                    f"[attempt {attempt_no} result] failed at stage "
                    f"'{failure_stage}': {failure_detail[:800]}"
                ),
            })
            # Plan returned UNCHANGED after a verify-stage failure (geometry was
            # fine, e.g. verifier_error) → skip regenerate next round, re-verify only.
            reuse_geometry = geometry_ok and rep.plan_dict == plan_dict
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
