"""eval/benchmark.py
====================
Evaluation harness for the Geometry Agent Harness (GAH-v2).

Runs the full pipeline on the T1/T2/T3 benchmark dataset
(dataset_v2/) and collects:
  - Execution success rate (did CadQuery produce a valid STL?)
  - CD / F1 / IoU against reference STLs
  - Failure category labels from the geometry loop trace
  - Per-tier aggregated statistics

This runs the pipeline **directly** (no Temporal dependency) by calling
execute_cadquery with the reference_code from each dataset entry.
For a production Temporal-backed run, use `--mode temporal` (NYI).

Usage:
    # Dry-run — just list entries, no execution
    python -m eval.benchmark --experiment-name test --dry-run

    # Single-tier validation run (2 entries per tier)
    python -m eval.benchmark --experiment-name val_t1 --tiers T1 --limit-per-tier 2

    # Full T1 run
    python -m eval.benchmark --experiment-name full_t1 --tiers T1

    # Run specific entry IDs
    python -m eval.benchmark --experiment-name smoke --ids T1_001 T1_005

    # Resume a partial run (already-completed IDs are skipped automatically)
    python -m eval.benchmark --experiment-name full_t1 --tiers T1

Results land in:
    eval_results/<experiment_name>/results.jsonl    — one JSON record per entry
    eval_results/<experiment_name>/config.json      — run configuration
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
from dotenv import load_dotenv

# ── Project root & env ----------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_PROJECT_ROOT / ".env")

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── Paths -----------------------------------------------------------------------

DATASET_DIR = _PROJECT_ROOT / "dataset_v2"
RESULTS_BASE_DIR = _PROJECT_ROOT / "eval_results"

TIER_FILES: dict[str, str] = {
    "T1": "t1_primitives.jsonl",
    "T2": "t2_engineering_parts.jsonl",
    "T3": "t3_complex_parts.jsonl",
}


# ── Dataset loader --------------------------------------------------------------


def load_entries(tiers: list[str], limit_per_tier: int = 0) -> list[dict]:
    """Load benchmark entries from the dataset_v2 JSONL files.

    Args:
        tiers: Which tiers to load, e.g. ["T1", "T2"].
        limit_per_tier: Cap per tier (0 = all).

    Returns:
        Flat list of entry dicts in the order they were loaded.
    """
    entries: list[dict] = []
    for tier in tiers:
        filename = TIER_FILES.get(tier)
        if not filename:
            print(f"WARNING: Unknown tier '{tier}', skipping")
            continue
        filepath = DATASET_DIR / filename
        if not filepath.exists():
            print(f"WARNING: {filepath} not found, skipping")
            continue

        tier_entries: list[dict] = []
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line:
                    tier_entries.append(json.loads(line))

        if limit_per_tier > 0:
            tier_entries = tier_entries[:limit_per_tier]

        entries.extend(tier_entries)
        print(f"  {tier}: {len(tier_entries)} entries loaded")

    return entries


# ── Reference STL ---------------------------------------------------------------


def get_reference_stl_path(entry_id: str) -> Optional[Path]:
    """Return the pre-baked reference STL path, or None if it doesn't exist.

    Reference STLs are generated once and committed to dataset_v2/reference_stls/.
    The benchmark never re-generates them — if one is missing, that entry is
    scored without geometry metrics.
    """
    path = DATASET_DIR / "reference_stls" / f"{entry_id}.stl"
    return path if path.exists() else None


# ── Single-entry runner ---------------------------------------------------------


def _classify_exception(exc: Exception) -> tuple[str, str]:
    """Map a thrown exception to a failure category so infra failures (API
    timeout, rate-limit, connection) are distinguished from geometry failures —
    they must NOT be counted against the geometry gates."""
    s = str(exc).lower()
    if any(k in s for k in ("timeout", "timed out", "deadline exceeded")):
        return "api_timeout", str(exc)
    if any(k in s for k in ("rate limit", "429", "quota", "resource exhausted")):
        return "api_rate_limit", str(exc)
    if any(k in s for k in ("budget", "max_money", "money spent")):
        return "budget_exhausted", str(exc)
    if any(k in s for k in ("connection", "unreachable", "refused", "name resolution",
                            "502", "503", "504", "bad gateway")):
        return "infra_error", str(exc)
    if any(k in s for k in ("did not finish", "function stack", "subagent died", "no final")):
        return "planner_error", str(exc)
    return "geometry_invalidity", str(exc)


def _run_full_loop_entry(entry: dict, base_record: dict, backend_url: str) -> dict:
    """Run the REAL agent loop (plan -> execute -> inspect -> render -> verify ->
    replan) for one entry and score it against the PRD gates.

    Pulls first-pass/repair/duration from the geometry-loop LoopResult + trace,
    and (if a reference STL exists) CD/F1/IoU against it. Requires a running
    backend at backend_url and a fast_rlm-capable environment (Deno)."""
    from backend.designs.runner import run_design_sync
    from tools.artifacts import new_run_id, run_dir
    from tools.load_trace import load_trace

    entry_id = entry["id"]
    prompt = entry.get("prompt", "")
    run_id = new_run_id(label=entry_id)
    start_time = time.time()

    try:
        result = run_design_sync(prompt, run_id, backend_url)
    except Exception as exc:
        category, reason = _classify_exception(exc)
        return {
            **base_record,
            "run_id": run_id,
            "total_time_ms": (time.time() - start_time) * 1000,
            "status": "failed",
            "failure_category": category,
            "failure_reason": reason,
            "error": str(exc),
        }

    elapsed_ms = (time.time() - start_time) * 1000
    outcome: dict = {}
    try:
        # load_trace returns {"success", "trace"}; the payload is under "trace".
        outcome = ((load_trace(run_id) or {}).get("trace") or {}).get("outcome", {}) or {}
    except Exception:
        pass

    stl = run_dir(run_id) / "solid.stl"
    stl_path = str(stl) if stl.exists() else None
    passed = result.status == "success"

    failure_category = result.failure_category
    failure_reason = outcome.get("failure_detail")
    if not passed and failure_reason:
        # The core trace's 6-category taxonomy (runtime/trace.py, PRD §14) has no
        # infra bucket — a timeout inside a replan retry surfaces through the
        # normal LoopResult path and falls back to geometry_invalidity, which
        # would misreport an API timeout as a geometry defect on the scorecard.
        # Reclassify from the failure TEXT for eval reporting only; the core
        # trace.json is untouched.
        eval_category, _ = _classify_exception(RuntimeError(failure_reason))
        if eval_category != "geometry_invalidity":
            failure_category = eval_category

    record: dict = {
        **base_record,
        "run_id": run_id,
        "execution_success": passed,
        "converged": passed,
        "num_iterations": result.attempts,           # 1 == first-pass success
        "total_time_ms": elapsed_ms,
        "duration_s": outcome.get("duration_s"),      # full-workflow wall-clock
        "status": result.status,
        "failure_category": failure_category,
        "failure_reason": failure_reason,
        "stl_path": stl_path,
    }

    # Optional fidelity metrics vs a reference STL, if one exists for this entry.
    ref_stl = get_reference_stl_path(entry_id)
    if ref_stl and stl_path:
        from tools.compute_mesh_metrics import compute_mesh_metrics

        m = compute_mesh_metrics(
            generated_stl_path=stl_path, reference_stl_path=str(ref_stl), use_icp=True
        )
        if m is not None:
            record["metrics"] = m
    return record


def run_single_entry(
    entry: dict,
    experiment_dir: Path,
    dry_run: bool,
    mode: str = "direct",
    backend_url: str = "http://localhost:8001",
) -> dict:
    """Execute one benchmark entry and return a scored result record.

    What happens inside:
      1. execute_cadquery() runs the entry's reference_code to produce a STL.
         (This is a "can the agent reproduce this?" baseline mode — in the
         Temporal mode the RLM writes the code instead.)
      2. compute_mesh_metrics() compares the generated STL to the reference.
      3. The record is returned for appending to results.jsonl.

    Args:
        entry:          A dataset entry dict with id, tier, prompt, reference_code.
        experiment_dir: The experiment's output directory (for artefact paths).
        dry_run:        If True, skip execution and return a placeholder record.

    Returns:
        A flat dict suitable for JSON serialisation to results.jsonl.
    """
    from tools.artifacts import new_run_id, run_dir
    from tools.compute_mesh_metrics import compute_mesh_metrics
    from tools.execute_cadquery import execute_cadquery

    entry_id: str = entry["id"]
    tier: str = entry.get("tier", "unknown")
    prompt: str = entry.get("prompt", "")
    reference_code: str = entry.get("reference_code", "")

    # Base record filled in on all code paths (dry_run, error, success).
    base_record: dict = {
        "id": entry_id,
        "tier": tier,
        "prompt": prompt,
        "execution_success": False,
        "converged": False,       # True when geometry executed + metrics computed
        "num_iterations": 1,      # Direct mode: 1 attempt, no replanning
        "num_llm_calls": 0,       # Direct mode: no LLM calls
        "total_time_ms": 0.0,
        "metrics": None,
        "failure_category": None,
        "failure_reason": None,
        "stl_path": None,
        "error": None,
    }

    if dry_run:
        print(f"  [DRY RUN] {entry_id} | {prompt[:70]}")
        return {**base_record, "dry_run": True}

    # Full agent-loop mode: the RLM plans, CadQuery runs the RLM's code, the
    # replanner repairs on failure — the actual pipeline the PRD gates measure
    # (first-pass %, repair iters, workflow duration). Reference-code ("direct")
    # mode below only tests whether CadQuery can reproduce the reference snippet.
    if mode == "full":
        return _run_full_loop_entry(entry, base_record, backend_url)

    if not reference_code:
        return {
            **base_record,
            "failure_category": "primitive_gap",
            "failure_reason": "No reference_code in dataset entry",
        }

    # Unique run folder for this entry so artefacts don't collide.
    run_id = new_run_id(label=entry_id)
    start_time = time.time()

    try:
        exec_result = execute_cadquery(reference_code, run_id)
        elapsed_ms = (time.time() - start_time) * 1000

        if not exec_result.get("success"):
            return {
                **base_record,
                "total_time_ms": elapsed_ms,
                "failure_category": "geometry_invalidity",
                "failure_reason": exec_result.get("error", "CadQuery execution failed"),
                "error": exec_result.get("error"),
            }

        # Execution succeeded — we have a STL.
        stl_path = exec_result.get("stl_path", "")
        record: dict = {
            **base_record,
            "execution_success": True,
            "total_time_ms": elapsed_ms,
            "stl_path": stl_path,
        }

        # Compute CD / F1 / IoU if a reference STL exists.
        ref_stl = get_reference_stl_path(entry_id)
        if ref_stl and stl_path and os.path.exists(stl_path):
            metrics = compute_mesh_metrics(
                generated_stl_path=stl_path,
                reference_stl_path=str(ref_stl),
                use_icp=True,
            )
            if metrics is not None:
                record["metrics"] = metrics
                record["converged"] = True
            else:
                record["failure_reason"] = "compute_mesh_metrics returned None"
        else:
            record["failure_reason"] = (
                f"No reference STL for {entry_id}" if ref_stl is None
                else "STL file missing after execution"
            )

        return record

    except Exception as exc:
        elapsed_ms = (time.time() - start_time) * 1000
        return {
            **base_record,
            "total_time_ms": elapsed_ms,
            "failure_category": "geometry_invalidity",
            "failure_reason": str(exc),
            "error": str(exc),
        }


# ── Main benchmark runner -------------------------------------------------------


def run_benchmark(args: argparse.Namespace) -> None:
    """Orchestrate the full benchmark: load → execute → score → save → summarise."""
    experiment_dir = RESULTS_BASE_DIR / args.experiment_name
    experiment_dir.mkdir(parents=True, exist_ok=True)

    results_file = experiment_dir / "results.jsonl"
    config_file = experiment_dir / "config.json"

    # Save run configuration for reproducibility.
    config = {
        "experiment_name": args.experiment_name,
        "dataset": "dataset_v2",
        "tiers": args.tiers,
        "limit_per_tier": args.limit_per_tier,
        "dry_run": args.dry_run,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": args.mode,
        "backend_url": args.backend_url,
    }
    with open(config_file, "w") as f:
        json.dump(config, f, indent=2)
    print(f"Config → {config_file}")

    # Load entries.
    print(f"\nLoading benchmark entries…")
    entries = load_entries(args.tiers, limit_per_tier=args.limit_per_tier)

    # Filter to specific IDs if requested.
    if args.ids:
        id_set = set(args.ids)
        entries = [e for e in entries if e["id"] in id_set]
        print(f"Filtered to {len(entries)} entries: {args.ids}")

    # Resume: skip already-completed IDs (so we can restart safely mid-run).
    completed_ids: set[str] = set()
    if results_file.exists() and not args.ids:
        with open(results_file) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    completed_ids.add(r["id"])
                except (json.JSONDecodeError, KeyError):
                    continue

    remaining = [e for e in entries if e["id"] not in completed_ids]
    print(
        f"Total: {len(entries)} | Already done: {len(completed_ids)} | "
        f"Remaining: {len(remaining)}\n"
    )

    if not remaining:
        print("All entries already completed.")
        _print_summary(args.experiment_name, results_file)
        return

    if args.dry_run:
        print(f"DRY RUN — listing {len(remaining)} entries:")
        for e in remaining:
            print(f"  [{e.get('tier', '?')}] {e['id']}: {e['prompt'][:70]}")
        return

    # Execute entries one by one.
    total_done = 0
    cd_vals: list[float] = []
    f1_vals: list[float] = []
    iou_vals: list[float] = []
    tier_stats: dict[str, dict] = {}

    for i, entry in enumerate(remaining):
        tier = entry.get("tier", "?")
        abs_idx = total_done + len(completed_ids) + 1
        print(
            f"\n[{abs_idx}/{len(entries)}] {entry['id']} ({tier}): "
            f"{entry['prompt'][:65]}…",
            flush=True,
        )

        try:
            record = run_single_entry(
                entry=entry,
                experiment_dir=experiment_dir,
                dry_run=False,
                mode=args.mode,
                backend_url=args.backend_url,
            )
        except Exception as exc:
            # A hard crash in one entry must NEVER stop the sweep — record it as a
            # harness failure and move on (results are appended so nothing is lost).
            print(f"  !! harness error on {entry['id']}: {exc}", flush=True)
            record = {
                "id": entry["id"], "tier": tier, "prompt": entry.get("prompt", ""),
                "execution_success": False, "converged": False, "num_iterations": 0,
                "total_time_ms": 0.0, "status": "failed",
                "failure_category": "harness_error", "failure_reason": str(exc),
                "error": str(exc),
            }

        # Append immediately so partial runs are resumable.
        with open(results_file, "a") as f:
            f.write(json.dumps(record) + "\n")

        total_done += 1

        # Update per-tier accumulators.
        if tier not in tier_stats:
            tier_stats[tier] = {"total": 0, "exec": 0, "conv": 0, "cd": [], "f1": [], "iou": []}
        ts = tier_stats[tier]
        ts["total"] += 1
        if record.get("execution_success"):
            ts["exec"] += 1
        if record.get("converged"):
            ts["conv"] += 1
        if m := record.get("metrics"):
            if m.get("chamfer_distance") is not None:
                ts["cd"].append(m["chamfer_distance"])
                ts["f1"].append(m["f1_score"])
                ts["iou"].append(m["volumetric_iou"])
                cd_vals.append(m["chamfer_distance"])
                f1_vals.append(m["f1_score"])
                iou_vals.append(m["volumetric_iou"])

        # Per-entry summary line.
        print(
            f"  exec={record.get('execution_success')}  "
            f"conv={record.get('converged')}  "
            f"time={record.get('total_time_ms', 0) / 1000:.1f}s"
        )
        if m := record.get("metrics"):
            print(
                f"  CD={m['chamfer_distance']:.4f}  "
                f"F1={m['f1_score']:.4f}  "
                f"IoU={m['volumetric_iou']:.4f}"
            )
        elif record.get("error"):
            print(f"  ERROR: {record['error'][:120]}")

    _print_final_summary(
        experiment_name=args.experiment_name,
        total_done=total_done,
        tier_stats=tier_stats,
        cd_vals=cd_vals,
        f1_vals=f1_vals,
        iou_vals=iou_vals,
        results_file=results_file,
    )
    if args.mode == "full":
        _print_prd_gates(results_file)


def _print_prd_gates(results_file: Path) -> None:
    """Score the run against the PRD single-part decision-metric gates."""
    if not results_file.exists():
        return
    recs = []
    with open(results_file) as f:
        for line in f:
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    recs = [r for r in recs if not r.get("dry_run")]
    n = len(recs)
    if not n:
        return
    passed = [r for r in recs if r.get("status") == "success"]
    first_pass = [r for r in passed if r.get("num_iterations") == 1]
    reps = [max(0, (r.get("num_iterations") or 1) - 1) for r in recs]
    durs = [r["duration_s"] for r in recs if isinstance(r.get("duration_s"), (int, float))]
    traced = [r for r in recs if r.get("duration_s") is not None or r.get("failure_category") is not None or r.get("status")]
    over5 = [d for d in durs if d > 300]
    fp_pct = 100 * len(first_pass) / n
    avg_rep = sum(reps) / n
    avg_dur = sum(durs) / len(durs) if durs else None

    def gate(ok: bool) -> str:
        return "PASS" if ok else "FAIL"

    print("\n" + "=" * 60)
    print("PRD SINGLE-PART DECISION GATES")
    print("=" * 60)
    print(f"  Valid first-pass      : {fp_pct:5.0f}%   (>80%)   [{gate(fp_pct > 80)}]")
    print(f"  Avg repair iterations : {avg_rep:5.2f}    (<2)     [{gate(avg_rep < 2)}]")
    print(f"  Trace artifacts       : {100*len(traced)/n:5.0f}%   (100%)   [{gate(len(traced) == n)}]")
    if avg_dur is not None:
        # PRD gate is on the AVERAGE; outlier count is reported alongside, not
        # folded into the same pass/fail (a single slow T3 part must not flip an
        # otherwise-fast average to FAIL, and vice versa — keep them legible).
        print(f"  Avg workflow time     : {avg_dur:5.0f}s   (<300s)  [{gate(avg_dur < 300)}]"
              f"   ({len(over5)}/{len(durs)} runs over 5 min)")
    else:
        print(f"  Avg workflow time     :   n/a    (<300s)  [no duration recorded]")
    print(f"  Runs: {n} | success: {len(passed)} | first-pass: {len(first_pass)}")

    # Failure breakdown — infra (api_timeout/rate_limit/infra/harness) vs geometry,
    # so an API-timeout run isn't misread as a geometry-gate miss.
    fails = [r for r in recs if r.get("status") != "success"]
    if fails:
        from collections import Counter
        by_cat = Counter(r.get("failure_category") or "unknown" for r in fails)
        infra = {"api_timeout", "api_rate_limit", "infra_error", "harness_error", "budget_exhausted"}
        print(f"  Failures ({len(fails)}): " + ", ".join(f"{c}={k}" for c, k in by_cat.most_common()))
        infra_n = sum(k for c, k in by_cat.items() if c in infra)
        if infra_n:
            print(f"    ⚠ {infra_n} infra/harness failure(s) — NOT geometry gate misses")

    # Per-tier first-pass (T1/T2/T3 complexity breakdown).
    tiers = sorted({r.get("tier", "?") for r in recs})
    if len(tiers) > 1:
        print("  Per-tier first-pass:")
        for t in tiers:
            tr = [r for r in recs if r.get("tier") == t]
            fp = [r for r in tr if r.get("status") == "success" and r.get("num_iterations") == 1]
            print(f"    {t}: {100*len(fp)/len(tr):4.0f}%  ({len(fp)}/{len(tr)})")
    print("=" * 60)


def _print_summary(experiment_name: str, results_file: Path) -> None:
    """Print aggregated summary from an existing results.jsonl (for resume case)."""
    if not results_file.exists():
        return
    records = []
    with open(results_file) as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    cd_vals = [r["metrics"]["chamfer_distance"] for r in records if r.get("metrics")]
    f1_vals = [r["metrics"]["f1_score"] for r in records if r.get("metrics")]
    iou_vals = [r["metrics"]["volumetric_iou"] for r in records if r.get("metrics")]
    total_done = len(records)

    tier_stats: dict[str, dict] = {}
    for r in records:
        tier = r.get("tier", "?")
        if tier not in tier_stats:
            tier_stats[tier] = {"total": 0, "exec": 0, "conv": 0, "cd": [], "f1": [], "iou": []}
        tier_stats[tier]["total"] += 1
        if r.get("execution_success"):
            tier_stats[tier]["exec"] += 1
        if r.get("converged"):
            tier_stats[tier]["conv"] += 1
        if m := r.get("metrics"):
            if m.get("chamfer_distance") is not None:
                tier_stats[tier]["cd"].append(m["chamfer_distance"])
                tier_stats[tier]["f1"].append(m["f1_score"])
                tier_stats[tier]["iou"].append(m["volumetric_iou"])

    _print_final_summary(
        experiment_name=experiment_name,
        total_done=total_done,
        tier_stats=tier_stats,
        cd_vals=cd_vals,
        f1_vals=f1_vals,
        iou_vals=iou_vals,
        results_file=results_file,
    )


def _print_final_summary(
    *,
    experiment_name: str,
    total_done: int,
    tier_stats: dict[str, dict],
    cd_vals: list[float],
    f1_vals: list[float],
    iou_vals: list[float],
    results_file: Path,
) -> None:
    """Print a formatted final summary table to stdout."""
    total_exec = sum(ts["exec"] for ts in tier_stats.values())
    total_conv = sum(ts["conv"] for ts in tier_stats.values())

    print(f"\n{'='*70}")
    print(f"EXPERIMENT: {experiment_name}")
    print(f"{'='*70}")
    print(
        f"Total: {total_done} | "
        f"Exec OK: {total_exec}/{total_done} | "
        f"Scored: {total_conv}/{total_done}"
    )

    if cd_vals:
        print(f"\nOverall Metrics (n={len(cd_vals)}):")
        print(f"  CD  — median: {np.median(cd_vals):.4f}  mean: {np.mean(cd_vals):.4f}")
        print(f"  F1  — median: {np.median(f1_vals):.4f}  mean: {np.mean(f1_vals):.4f}")
        print(f"  IoU — median: {np.median(iou_vals):.4f}  mean: {np.mean(iou_vals):.4f}")

    if tier_stats:
        print(f"\nPer-Tier:")
        print(f"  {'Tier':<6} {'Exec%':>8} {'Conv%':>8} {'CD Med':>10} {'F1 Med':>10} {'IoU Med':>10}")
        print(f"  {'-'*6} {'-'*8} {'-'*8} {'-'*10} {'-'*10} {'-'*10}")
        for tier in sorted(tier_stats.keys()):
            ts = tier_stats[tier]
            exec_pct = ts["exec"] / ts["total"] * 100 if ts["total"] else 0.0
            conv_pct = ts["conv"] / ts["total"] * 100 if ts["total"] else 0.0
            cd_med = f"{np.median(ts['cd']):.4f}" if ts["cd"] else "—"
            f1_med = f"{np.median(ts['f1']):.4f}" if ts["f1"] else "—"
            iou_med = f"{np.median(ts['iou']):.4f}" if ts["iou"] else "—"
            print(
                f"  {tier:<6} {exec_pct:>7.1f}% {conv_pct:>7.1f}% "
                f"{cd_med:>10} {f1_med:>10} {iou_med:>10}"
            )

    print(f"\nResults : {results_file}")


# ── CLI entry point -------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GAH-v2 Benchmark Runner — evaluates the geometry pipeline against dataset_v2"
    )
    parser.add_argument(
        "--experiment-name", required=True,
        help="Unique name for this run (used as the results folder name)",
    )
    parser.add_argument(
        "--tiers", nargs="+", default=["T1", "T2", "T3"],
        choices=["T1", "T2", "T3"],
        help="Which dataset tiers to include (default: all)",
    )
    parser.add_argument(
        "--limit-per-tier", type=int, default=0,
        help="Max entries per tier, 0 = all (default: 0)",
    )
    parser.add_argument(
        "--ids", nargs="+", default=None,
        help="Run only specific entry IDs, e.g. --ids T1_001 T1_005",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List entries without executing anything",
    )
    parser.add_argument(
        "--mode", choices=["direct", "full"], default="direct",
        help="direct = run each entry's reference_code (fidelity baseline); "
             "full = run the real agent loop (planner writes code, replanner "
             "repairs) — measures the PRD first-pass/repair/duration gates",
    )
    parser.add_argument(
        "--backend-url", default="http://localhost:8001",
        help="Backend base URL the planner pull-tools hit (full mode only)",
    )
    args = parser.parse_args()
    run_benchmark(args)


if __name__ == "__main__":
    main()
