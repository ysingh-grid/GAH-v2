"""Temporal activities — thin @activity.defn wrappers around runtime/ functions.

Activities are the only place Temporal touches the real compute.
Each function is synchronous; Temporal's Worker runs sync activities in a
thread-pool executor automatically, keeping the asyncio event loop free.

Retry policy and timeouts are set on the workflow side, not here.
"""

from __future__ import annotations

from temporalio import activity

from runtime.compile_forge import compile_plan_to_forge
from runtime.loop import run_geometry_loop
from runtime.planner import PlannerOutput, run_planner_turn
from runtime.schema import PrimitivePlan, load_library
from temporal.shared import DesignInput, DesignResult


@activity.defn
def run_geometry_activity(inp: DesignInput) -> DesignResult:
    """Run the full geometry loop for one design.

    Calls run_geometry_loop (CadQuery + MeshLib + replan) and returns the
    outcome as a DesignResult.  The loop's internal replan calls go back
    through the in-process planner (not a fresh Temporal workflow) because
    they are sub-second and don't need separate durability.
    """
    library = load_library()
    plan = PrimitivePlan.model_validate(inp.plan_dict)
    planner_fn = _make_planner_fn(inp.backend_url)

    result = run_geometry_loop(
        original_prompt=inp.original_prompt,
        initial_plan=plan,
        planner_fn=planner_fn,
        library=library,
        run_id=inp.run_id,
    )

    return DesignResult(
        status=result.status,
        final_plan=result.final_plan or {},
        run_id=inp.run_id,
        failure_category=result.failure_category or "",
        message=result.message or "",
        question=result.question or "",
    )


@activity.defn
def compile_forge_activity(inp: DesignInput) -> str:
    """Compile the plan to a .forge.js string.

    Returns an empty string on any compilation error (the workflow treats
    that as a non-fatal degradation — the user still gets the plan).
    """
    try:
        library = load_library()
        plan = PrimitivePlan.model_validate(inp.plan_dict)
        return compile_plan_to_forge(plan, library)
    except Exception:
        return ""


# ── Internal ──────────────────────────────────────────────────────────────────

def _make_planner_fn(backend_url: str):  # noqa: ANN202
    """Return a closure that calls run_planner_turn with the right backend URL."""

    def _fn(original_prompt: str, history: list[dict[str, str]]) -> PlannerOutput:
        return run_planner_turn(original_prompt, history, backend_url=backend_url)

    return _fn
