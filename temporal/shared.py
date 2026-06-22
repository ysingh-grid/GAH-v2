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
    GENERATING = "generating"  # compile CadQuery + .forge.js IN PARALLEL, then
                               # execute CadQuery -> solid + render. Both compilers
                               # are deterministic from the same plan and mutually
                               # independent, so they run concurrently in one stage.
    INSPECTING = "inspecting"  # MeshLib watertight / manifold check
    REPAIRING = "repairing"    # MeshLib repair (only when inspect fails)
    VERIFYING = "verifying"    # multimodal verify against intent
    DONE = "done"
    FAILED = "failed"
    NEEDS_USER = "needs_user"


@dataclass
class DesignInput:
    """Everything the DesignWorkflow needs to produce a part."""

    original_prompt: str
    # PrimitivePlan serialised via runtime.schema.plan_to_dict() — JSON-safe.
    plan_dict: dict[str, Any]
    run_id: str
    backend_url: str = "http://localhost:8001"


@dataclass
class DesignResult:
    """Outcome returned by the DesignWorkflow to the workflow starter."""

    status: str  # "success" | "failed" | "needs_user"
    forge_js: str = ""
    final_plan: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    failure_category: str = ""
    message: str = ""
    question: str = ""


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
    """Result of one generate attempt (compile CQ+forge, execute, inspect, repair, render).

    On failure, `failure_stage` is one of: primitive_gap, cadquery_compile,
    cadquery_execute, mesh_repair, forge_compile — each routes to the replanner.
    """

    ok: bool
    failure_stage: str = ""
    failure_detail: str = ""
    code: str = ""        # compiled CadQuery source
    forge_js: str = ""    # compiled .forge.js (parallel with code)
    execution_result: dict[str, Any] = field(default_factory=dict)
    mesh_report: dict[str, Any] = field(default_factory=dict)
    renders: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerifyInput:
    """Input to verify_activity: prompt + geometry evidence for the multimodal judge."""

    prompt: str
    code: str
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
    """Input to replan_activity: the failure to fix + context for the no-tools replanner."""

    original_prompt: str
    last_plan_dict: dict[str, Any]
    failure_stage: str
    detail: str
    history: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ReplanOutput:
    """Replanner decision: a corrected plan, or a question escalated to the user."""

    action: str  # "plan_ready" | "ask_user"
    plan_dict: dict[str, Any] = field(default_factory=dict)
    question: str = ""


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
