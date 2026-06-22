"""eval/compute_metrics_posthoc.py
===================================
Post-hoc metrics computation for benchmark runs where CD/F1/IoU were skipped
(e.g. due to a MeshLib error during the original run).

Reads an existing results.jsonl, resolves the saved stl_path for each
entry that has execution_success=True but no metrics, computes CD/F1/IoU
against the reference STL, and writes an updated file alongside the original.

Usage:
    python -m eval.compute_metrics_posthoc --experiment-name <name>

Output files (written next to results.jsonl):
    eval_results/<name>/results_with_metrics.jsonl   — updated records
    eval_results/<name>/metrics_summary.json         — aggregate stats + gate check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

# ── Paths -----------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_BASE_DIR = _PROJECT_ROOT / "eval_results"
REF_STL_DIR = _PROJECT_ROOT / "dataset_v2" / "reference_stls"

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ── Phase-2 gate thresholds (CADSmith baseline, PRD §14) -----------------------

_CD_GATE  = 0.74    # mean CD ≤ this to pass
_F1_GATE  = 0.9846  # median F1 ≥ this to pass
_IOU_GATE = 0.9629  # median IoU ≥ this to pass


# ── Main -----------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Post-hoc CD/F1/IoU computation for completed benchmark runs"
    )
    parser.add_argument("--experiment-name", required=True,
                        help="Name of the experiment (matches a folder under eval_results/)")
    parser.add_argument("--no-icp", action="store_true", default=False,
                        help="Skip ICP alignment before computing distances (faster, less accurate)")
    args = parser.parse_args()

    from tools.compute_mesh_metrics import compute_mesh_metrics

    exp_dir = RESULTS_BASE_DIR / args.experiment_name
    results_file = exp_dir / "results.jsonl"

    if not results_file.exists():
        print(f"ERROR: {results_file} not found")
        sys.exit(1)

    with open(results_file) as f:
        records = [json.loads(line) for line in f if line.strip()]

    print(f"Loaded {len(records)} records from {results_file}")

    updated: list[dict] = []
    skipped = 0
    computed = 0
    cd_vals: list[float] = []
    f1_vals: list[float] = []
    iou_vals: list[float] = []
    tier_stats: dict[str, dict] = {}

    for rec in records:
        entry_id: str = rec["id"]
        tier: str = rec.get("tier", "?")

        # Pass through entries that already have metrics.
        if rec.get("metrics"):
            updated.append(rec)
            _accumulate(tier_stats, tier, rec["metrics"], cd_vals, f1_vals, iou_vals)
            continue

        # Skip entries without a successful STL.
        stl_path = rec.get("stl_path")
        if not stl_path or not rec.get("execution_success"):
            updated.append(rec)
            skipped += 1
            continue

        # Skip if the generated STL is no longer on disk.
        from pathlib import Path as _P
        if not _P(stl_path).exists():
            print(f"  [{entry_id}] STL not found on disk: {stl_path}")
            updated.append(rec)
            skipped += 1
            continue

        # Skip if reference STL doesn't exist.
        ref_stl = REF_STL_DIR / f"{entry_id}.stl"
        if not ref_stl.exists():
            print(f"  [{entry_id}] no reference STL — skipping")
            updated.append(rec)
            skipped += 1
            continue

        # Compute metrics.
        print(f"  [{entry_id}] computing metrics…", end=" ", flush=True)
        metrics = compute_mesh_metrics(
            generated_stl_path=stl_path,
            reference_stl_path=str(ref_stl),
            use_icp=not args.no_icp,
        )

        if metrics is not None:
            rec = {**rec, "metrics": metrics, "converged": True}
            _accumulate(tier_stats, tier, metrics, cd_vals, f1_vals, iou_vals)
            print(
                f"CD={metrics['chamfer_distance']:.4f}  "
                f"F1={metrics['f1_score']:.4f}  "
                f"IoU={metrics['volumetric_iou']:.4f}"
            )
            computed += 1
        else:
            print("FAILED — compute_mesh_metrics returned None")
            skipped += 1

        updated.append(rec)

    # Write updated results.
    out_file = exp_dir / "results_with_metrics.jsonl"
    with open(out_file, "w") as f:
        for r in updated:
            f.write(json.dumps(r) + "\n")

    # Print summary.
    print(f"\n{'='*70}")
    print(f"EXPERIMENT: {args.experiment_name}")
    print(f"{'='*70}")
    print(f"Computed: {computed} | Already had metrics: {len(records) - computed - skipped} | Skipped: {skipped}")

    if cd_vals:
        print(f"\nOverall Metrics (n={len(cd_vals)}):")
        print(f"  CD  — median: {np.median(cd_vals):.4f}  mean: {np.mean(cd_vals):.4f}")
        print(f"  F1  — median: {np.median(f1_vals):.4f}  mean: {np.mean(f1_vals):.4f}")
        print(f"  IoU — median: {np.median(iou_vals):.4f}  mean: {np.mean(iou_vals):.4f}")

        _print_per_tier(tier_stats)
        _print_gate_check(cd_vals, f1_vals, iou_vals)

        summary = _build_summary(args.experiment_name, cd_vals, f1_vals, iou_vals, tier_stats)
        summary_file = exp_dir / "metrics_summary.json"
        with open(summary_file, "w") as f:
            json.dump(summary, f, indent=2)

        print(f"\nUpdated : {out_file}")
        print(f"Summary : {summary_file}")


# ── Helpers --------------------------------------------------------------------


def _accumulate(
    tier_stats: dict[str, dict],
    tier: str,
    metrics: dict,
    cd_vals: list[float],
    f1_vals: list[float],
    iou_vals: list[float],
) -> None:
    """Add a metrics record to the per-tier accumulators and overall lists."""
    if metrics.get("chamfer_distance") is None:
        return
    if tier not in tier_stats:
        tier_stats[tier] = {"cd": [], "f1": [], "iou": []}
    tier_stats[tier]["cd"].append(metrics["chamfer_distance"])
    tier_stats[tier]["f1"].append(metrics["f1_score"])
    tier_stats[tier]["iou"].append(metrics["volumetric_iou"])
    cd_vals.append(metrics["chamfer_distance"])
    f1_vals.append(metrics["f1_score"])
    iou_vals.append(metrics["volumetric_iou"])


def _print_per_tier(tier_stats: dict[str, dict]) -> None:
    """Print the per-tier metrics table."""
    print(f"\nPer-Tier:")
    print(f"  {'Tier':<6} {'n':>4} {'CD Med':>10} {'CD Mean':>10} {'F1 Med':>10} {'IoU Med':>10}")
    print(f"  {'-'*6} {'-'*4} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")
    for tier in sorted(tier_stats.keys()):
        ts = tier_stats[tier]
        n = len(ts["cd"])
        if n == 0:
            continue
        print(
            f"  {tier:<6} {n:>4} "
            f"{np.median(ts['cd']):>10.4f} "
            f"{np.mean(ts['cd']):>10.4f} "
            f"{np.median(ts['f1']):>10.4f} "
            f"{np.median(ts['iou']):>10.4f}"
        )


def _print_gate_check(
    cd_vals: list[float],
    f1_vals: list[float],
    iou_vals: list[float],
) -> None:
    """Print the Phase-2 gate check against the CADSmith baseline."""
    cd_pass  = np.mean(cd_vals)   <= _CD_GATE
    f1_pass  = np.median(f1_vals) >= _F1_GATE
    iou_pass = np.median(iou_vals) >= _IOU_GATE

    print(f"\n{'='*70}")
    print(f"PHASE 2 GATE CHECK  (CADSmith baseline: CD≤{_CD_GATE}, F1≥{_F1_GATE}, IoU≥{_IOU_GATE})")
    print(f"  CD  mean   {np.mean(cd_vals):.4f}   {'PASS ✓' if cd_pass else 'FAIL ✗'}")
    print(f"  F1  median {np.median(f1_vals):.4f}   {'PASS ✓' if f1_pass else 'FAIL ✗'}")
    print(f"  IoU median {np.median(iou_vals):.4f}   {'PASS ✓' if iou_pass else 'FAIL ✗'}")
    gate = cd_pass and f1_pass and iou_pass
    print(f"\n  GATE: {'PASSED ✓' if gate else 'NOT PASSED ✗'}")


def _build_summary(
    experiment: str,
    cd_vals: list[float],
    f1_vals: list[float],
    iou_vals: list[float],
    tier_stats: dict[str, dict],
) -> dict:
    """Build the JSON summary dict saved to metrics_summary.json."""
    cd_pass  = float(np.mean(cd_vals))   <= _CD_GATE
    f1_pass  = float(np.median(f1_vals)) >= _F1_GATE
    iou_pass = float(np.median(iou_vals)) >= _IOU_GATE

    return {
        "experiment": experiment,
        "n_with_metrics": len(cd_vals),
        "cd_median": float(np.median(cd_vals)),
        "cd_mean": float(np.mean(cd_vals)),
        "f1_median": float(np.median(f1_vals)),
        "f1_mean": float(np.mean(f1_vals)),
        "iou_median": float(np.median(iou_vals)),
        "iou_mean": float(np.mean(iou_vals)),
        "gate_passed": bool(cd_pass and f1_pass and iou_pass),
        "gate_thresholds": {
            "cd_mean_max": _CD_GATE,
            "f1_median_min": _F1_GATE,
            "iou_median_min": _IOU_GATE,
        },
        "per_tier": {
            t: {
                "n": len(ts["cd"]),
                "cd_median": float(np.median(ts["cd"])) if ts["cd"] else None,
                "cd_mean":   float(np.mean(ts["cd"]))   if ts["cd"] else None,
                "f1_median": float(np.median(ts["f1"])) if ts["f1"] else None,
                "iou_median": float(np.median(ts["iou"])) if ts["iou"] else None,
            }
            for t, ts in tier_stats.items()
        },
    }


if __name__ == "__main__":
    main()
