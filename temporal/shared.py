"""Shared dataclasses passed between the Temporal workflow and its activities.

Must be JSON-serialisable (Temporal's default codec is JSON).
Plain dataclasses with primitive fields satisfy this requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class DesignStage:
    """Coarse pipeline stages (architecture diagram 03.1) the workflow advances through.

    The workflow holds the current stage and exposes it via a @workflow.query, so
    the backend can poll it and stream live progress to the chat UI. Each value
    also marks a Temporal activity boundary, so the Temporal UI timeline shows the
    SAME stages — both observability surfaces read one vocabulary.

    Plain string constants (not an enum) keep the workflow query JSON-trivial.
    """

    PLANNING = "planning"      # planner turn (runs in backend before the workflow)
    GENERATING = "generating"  # compile CadQuery, execute -> solid + STL, inspect/repair.
    INSPECTING = "inspecting"  # MeshLib watertight / manifold check
    REPAIRING = "repairing"    # MeshLib repair (only when inspect fails)
    VERIFYING = "verifying"    # multimodal verify against intent
    REPLANNING = "replanning"  # scoped replanner fixing the plan after a failure (loop-back)
    DONE = "done"
    FAILED = "failed"


@dataclass
class DesignInput:
    """Everything the DesignWorkflow needs to produce a part."""

    original_prompt: str
    # PrimitivePlan serialised via runtime.schema.plan_to_dict() — JSON-safe.
    plan_dict: dict[str, Any]
    run_id: str
    backend_url: str = "http://localhost:8001"
    # Base replan history: the pre-planner intake facts ONLY (never the raw
    # chatbot conversation). The workflow appends each round's failed plan +
    # failure on top, so every replan sees the full plan lineage.
    history: list[dict[str, str]] = field(default_factory=list)


@dataclass
class DesignResult:
    """Outcome returned by the DesignWorkflow to the workflow starter."""

    status: str  # "success" | "failed"
    final_plan: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    failure_category: str = ""
    message: str = ""


# ── Per-activity I/O contracts ──────────────────────────────────────────────────
# One coarse activity per pipeline stage. Heavy artifacts (STL, PNG) stay on disk
# under outputs/{run_id}/; these payloads carry only small metadata + code strings
# + path references, well under Temporal's payload limit (diagram 03.2: "stores
# heavy primitive detail by artifact reference").


@dataclass
class GenerateInput:
    """Input to generate_activity: the plan to realise + the run's artifact id."""

    plan_dict: dict[str, Any]
    run_id: str


@dataclass
class GenerateOutput:
    """Result of one generate attempt (compile CQ, execute, inspect, repair, render).

    On failure, `failure_stage` is one of: primitive_gap, cadquery_compile,
    cadquery_execute, mesh_repair — each routes to the replanner.

    NOTE: superseded by the per-step activities below (compile/execute/inspect/
    repair/render) so the Temporal timeline shows each step distinctly. Kept for the
    in-process loop's GenerateOutput shape and back-compat; the workflow no longer
    uses generate_activity.
    """

    ok: bool
    failure_stage: str = ""
    failure_detail: str = ""
    code: str = ""        # compiled CadQuery source
    execution_result: dict[str, Any] = field(default_factory=dict)
    mesh_report: dict[str, Any] = field(default_factory=dict)
    renders: dict[str, Any] = field(default_factory=dict)


# ── Per-step generate activities (the split of generate_activity) ────────────────
# Each is ONE Temporal activity → one timeline event, repeated every replan loop.
# Heavy artifacts (STL) are passed by FILE PATH on the shared ./outputs volume, so
# the Temporal payloads stay small (just paths + metadata + the code string).


@dataclass
class CompileInput:
    plan_dict: dict[str, Any]
    run_id: str


@dataclass
class CompileOutput:
    ok: bool
    code: str = ""
    failure_stage: str = ""   # primitive_gap | cadquery_compile
    failure_detail: str = ""


@dataclass
class ExecuteInput:
    code: str
    run_id: str


@dataclass
class ExecuteOutput:
    ok: bool
    execution_result: dict[str, Any] = field(default_factory=dict)
    stl_path: str = ""
    failure_stage: str = ""   # cadquery_execute
    failure_detail: str = ""


@dataclass
class InspectInput:
    stl_path: str


@dataclass
class InspectOutput:
    passes: bool
    mesh_report: dict[str, Any] = field(default_factory=dict)


@dataclass
class RepairInput:
    stl_path: str
    run_id: str


@dataclass
class RepairOutput:
    passes: bool
    mesh_report: dict[str, Any] = field(default_factory=dict)
    repaired_stl_path: str = ""
    failure_stage: str = ""   # mesh_repair
    failure_detail: str = ""


@dataclass
class RenderInput:
    stl_path: str
    run_id: str
    section: dict[str, Any] | None = None


@dataclass
class RenderOutput:
    ok: bool
    renders: dict[str, Any] = field(default_factory=dict)
    failure_stage: str = ""   # cadquery_execute (render failure)
    failure_detail: str = ""


@dataclass
class VerifyInput:
    """Input to verify_activity: prompt + geometry evidence for the multimodal judge.

    Deliberately NO CadQuery code field: the VLM judge reads only the prompt,
    render PNG, and last replan feedback — shipping the code here made it show
    up in the Temporal UI payload and look like it was being sent to the judge.
    """

    prompt: str
    execution_result: dict[str, Any]
    mesh_report: dict[str, Any]
    renders: dict[str, Any]
    prior_feedback: list[str] = field(default_factory=list)


@dataclass
class VerifyOutput:
    """Verifier verdict: did the geometry match the user's intent?"""

    passed: bool
    feedback: str = ""
    verdict: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplanInput:
    """Input to replan_activity: the failure to fix + context for the scoped replanner."""

    original_prompt: str
    last_plan_dict: dict[str, Any]
    failure_stage: str
    detail: str
    history: list[dict[str, str]] = field(default_factory=list)
    backend_url: str = ""  # so the worker-side replanner's pull tools can reach the backend


@dataclass
class ReplanOutput:
    """Replanner outcome: a corrected plan, or a categorized failure.

    There is no ask_user branch — the replanner always attempts a fix; ok=False
    means it could not (exception, exhausted budget), not that it asked a question.
    """

    ok: bool
    plan_dict: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class TraceInput:
    """Everything record_trace_activity needs to write the auditable trace.json."""

    run_id: str
    prompt: str
    plan_dict: dict[str, Any]
    code: str
    execution_result: dict[str, Any]
    mesh_report: dict[str, Any]
    renders: dict[str, Any]
    verdict: dict[str, Any]
    status: str
    attempts: int
    failure_stage: str = ""
    failure_detail: str = ""
