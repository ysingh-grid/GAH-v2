"""Capability harness — repeatable pass-rate measurement for the geometry uplift.

WHY THIS EXISTS
The uplift (grounded planner + precise verifier) must be judged by one number:
does a fixed set of representative prompts produce geometry that *matches the
request*? This harness is that instrument. Run it before and after each pillar
to quantify the change instead of arguing from vibes.

Two independent capabilities, both feeding one markdown table:

  1. scan_existing_traces(outputs_dir)  — read the trace.json files already on
     disk and tabulate status + failure_category. This is the honest "before"
     snapshot: real historical runs, no live model needed.

  2. run_suite(cases, run_fn)           — run the curated CASES live through the
     in-process planner -> geometry loop. `run_fn` is DEPENDENCY-INJECTED so the
     harness is unit-testable with a stub (no LLM / Deno / network), and the live
     wiring lives in make_live_run_fn().

Live run (needs backend on :8001, deno, GEMINI_API_KEY, cadquery+meshlib):
    uv run python -m eval.capability_harness --backend-url http://localhost:8001
    uv run python -m eval.capability_harness --scan-only     # just tabulate outputs/
"""

from __future__ import annotations

import argparse
import json
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runtime.schema import PrimitivePlan

_REPO = Path(__file__).resolve().parent.parent
_OUTPUTS = _REPO / "outputs"

# ── The curated prompt set ────────────────────────────────────────────────────
# Six prompts spanning the three difficulty tiers. The t3 laptop-stand prompt is
# copied VERBATIM from the failing traces so the harness measures the exact case
# that motivated this work.


@dataclass(frozen=True)
class CapabilityCase:
    """One prompt to run, tagged with its difficulty tier."""

    id: str
    tier: str  # "t1" primitive | "t2" engineering | "t3" complex/assembly
    prompt: str


CASES: tuple[CapabilityCase, ...] = (
    CapabilityCase("t1_cube", "t1", "Create a cube 40 mm on each side."),
    CapabilityCase(
        "t1_tube", "t1",
        "Make a hollow cylinder with outer radius 20 mm, inner radius 15 mm, height 50 mm.",
    ),
    CapabilityCase(
        "t2_mount_plate", "t2",
        "Design a rectangular mounting plate 100 x 60 x 8 mm with four M5 clearance "
        "holes 10 mm in from each corner.",
    ),
    CapabilityCase(
        "t2_l_bracket", "t2",
        "Create an L-bracket: two 80 x 60 mm flanges meeting at a right angle, 5 mm "
        "thick, with two mounting holes on each flange.",
    ),
    CapabilityCase(
        "t3_laptop_stand", "t3",
        "Create a foldable laptop stand with two side frames connected by hinge pins.\n"
        "Add adjustable angle slots, ventilation cutouts, and rubber foot recesses on "
        "the base.\nUse rounded edges and keep the structure lightweight but stable",
    ),
    CapabilityCase(
        "t3_spoked_wheel", "t3",
        "Design a spoked wheel: a central hub, an outer rim, and six spokes connecting "
        "the hub to the rim.",
    ),
)


@dataclass
class CaseResult:
    """Flat outcome record for one case — the row of the pass-rate table."""

    id: str
    tier: str
    prompt: str
    status: str  # "success" | "failed" | "exception"
    failure_category: str | None = None
    attempts: int = 0
    detail: str = ""
    run_id: str = ""
    error: str | None = None


# A run function turns a case into a result. Injected so run_suite is testable.
RunFn = Callable[[CapabilityCase], CaseResult]


def run_suite(cases: tuple[CapabilityCase, ...], run_fn: RunFn) -> list[CaseResult]:
    """Run every case through `run_fn`, never aborting the suite on one failure."""
    results: list[CaseResult] = []
    for case in cases:
        try:
            results.append(run_fn(case))
        except Exception:  # noqa: BLE001 — a crash is itself a recorded outcome
            results.append(
                CaseResult(
                    id=case.id,
                    tier=case.tier,
                    prompt=case.prompt,
                    status="exception",
                    error=traceback.format_exc()[-2000:],
                )
            )
    return results


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    """Aggregate pass-rate overall and per tier, plus a failure-category tally."""
    total = len(results)
    passed = sum(1 for r in results if r.status == "success")
    by_tier: dict[str, dict[str, int]] = {}
    by_category: dict[str, int] = {}
    for r in results:
        tier = by_tier.setdefault(r.tier, {"passed": 0, "total": 0})
        tier["total"] += 1
        if r.status == "success":
            tier["passed"] += 1
        else:
            key = r.failure_category or r.status
            by_category[key] = by_category.get(key, 0) + 1
    return {
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "by_tier": by_tier,
        "by_category": by_category,
    }


def to_markdown_table(results: list[CaseResult]) -> str:
    """Render results + summary as a markdown block suitable for fix.md."""
    lines = [
        "| id | tier | status | failure_category | attempts | detail |",
        "|----|------|--------|------------------|----------|--------|",
    ]
    for r in sorted(results, key=lambda x: (x.tier, x.id)):
        detail = (r.detail or r.error or "").replace("\n", " ")[:60]
        lines.append(
            f"| {r.id} | {r.tier} | {r.status} | {r.failure_category or '-'} "
            f"| {r.attempts} | {detail} |"
        )
    s = summarize(results)
    lines.append("")
    lines.append(f"**Pass rate: {s['passed']}/{s['total']} ({s['pass_rate'] * 100:.0f}%)**")
    tiers = ", ".join(
        f"{t}: {v['passed']}/{v['total']}" for t, v in sorted(s["by_tier"].items())
    )
    lines.append(f"By tier — {tiers}")
    if s["by_category"]:
        cats = ", ".join(f"{k}: {n}" for k, n in sorted(s["by_category"].items()))
        lines.append(f"Failure categories — {cats}")
    return "\n".join(lines)


def scan_existing_traces(outputs_dir: Path = _OUTPUTS) -> list[CaseResult]:
    """Tabulate the trace.json files already on disk into CaseResults.

    The honest "before" snapshot — reads real historical runs, no model call.
    Each run's tier is unknown from the trace alone, so it is bucketed as "hist".
    """
    results: list[CaseResult] = []
    if not outputs_dir.exists():
        return results
    for trace_path in sorted(outputs_dir.glob("*/trace.json")):
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        outcome = trace.get("outcome") or {}
        results.append(
            CaseResult(
                id=trace.get("run_id", trace_path.parent.name)[:24],
                tier="hist",
                prompt=(trace.get("prompt") or "").splitlines()[0][:60],
                status=outcome.get("status") or "unknown",
                failure_category=outcome.get("failure_category"),
                attempts=int(outcome.get("attempts") or 0),
                detail=(outcome.get("failure_detail") or "")[:60],
                run_id=trace.get("run_id", ""),
            )
        )
    return results


def make_live_run_fn(*, backend_url: str, verify: bool = True) -> RunFn:
    """Build the real run function: planner -> geometry loop, in-process.

    Imports are local so the module (and its unit tests) import without pulling
    in cadquery/meshlib/fast-rlm. Mirrors eval.run_dataset_v2._run_one.
    """

    def _run(case: CapabilityCase) -> CaseResult:
        from runtime.loop import run_geometry_loop
        from runtime.planner import run_planner_turn, run_replanner_turn
        from runtime.schema import load_library

        plan = run_planner_turn(case.prompt, [], backend_url=backend_url)

        def planner_fn(original_prompt: str, history: list[dict[str, str]]) -> PrimitivePlan:
            return run_replanner_turn(original_prompt, history, backend_url=backend_url)

        result = run_geometry_loop(
            original_prompt=case.prompt,
            initial_plan=plan,
            planner_fn=planner_fn,
            library=load_library(),
            run_id=case.id,
            verify=verify,
        )
        return CaseResult(
            id=case.id,
            tier=case.tier,
            prompt=case.prompt,
            status=result.status,
            failure_category=result.failure_category,
            attempts=result.attempts,
            detail=result.message,
            run_id=result.run_id,
        )

    return _run


def main() -> None:
    """CLI: run the curated suite live, or just scan existing traces."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend-url", default="http://localhost:8001")
    ap.add_argument("--no-verify", action="store_true", help="skip the multimodal verifier")
    ap.add_argument("--scan-only", action="store_true", help="just tabulate outputs/ traces")
    ap.add_argument("--out", default="", help="write the markdown table to this file")
    args = ap.parse_args()

    if args.scan_only:
        results = scan_existing_traces()
    else:
        run_fn = make_live_run_fn(backend_url=args.backend_url, verify=not args.no_verify)
        results = run_suite(CASES, run_fn)

    table = to_markdown_table(results)
    print(table)
    if args.out:
        Path(args.out).write_text(table + "\n", encoding="utf-8")
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
