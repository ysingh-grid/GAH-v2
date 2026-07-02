"""
harness/eval/eval_compare.py
============================
A/B testing and comparison script for Phase 2 eval runs.

Compares the results of an eval run (from eval_runner.py/benchmark.py)
against a baseline zero-shot dataset, computing the delta in Chamfer Distance,
F1 Score, and Volumetric IoU.

Usage:
  python3 -m harness.eval.eval_compare --baseline eval_results/baseline --run eval_results/phase2_run
"""

import argparse
import json
import numpy as np
from pathlib import Path
import sys

def load_results(results_dir: str) -> dict:
    results_path = Path(results_dir) / "results.jsonl"
    if not results_path.exists():
        print(f"Error: {results_path} not found.")
        sys.exit(1)
        
    records = {}
    with open(results_path) as f:
        for line in f:
            try:
                rec = json.loads(line.strip())
                records[rec["id"]] = rec
            except Exception:
                continue
    return records

def print_metrics(name: str, records: dict):
    cd_vals = []
    f1_vals = []
    iou_vals = []
    exec_success = 0
    total = len(records)
    
    for r in records.values():
        if r.get("execution_success"):
            exec_success += 1
        m = r.get("metrics")
        if m and m.get("chamfer_distance") is not None:
            cd_vals.append(m["chamfer_distance"])
            f1_vals.append(m["f1_score"])
            iou_vals.append(m["volumetric_iou"])
            
    print(f"\n[{name}] Total: {total} | Exec Success: {exec_success} ({(exec_success/total*100) if total else 0:.1f}%)")
    if cd_vals:
        print(f"  CD  — median: {np.median(cd_vals):.4f}, mean: {np.mean(cd_vals):.4f}")
        print(f"  F1  — median: {np.median(f1_vals):.4f}, mean: {np.mean(f1_vals):.4f}")
        print(f"  IoU — median: {np.median(iou_vals):.4f}, mean: {np.mean(iou_vals):.4f}")
    return cd_vals, f1_vals, iou_vals

def compare(baseline_dir: str, run_dir: str):
    print(f"Comparing Baseline ({baseline_dir}) vs Run ({run_dir})")
    
    b_records = load_results(baseline_dir)
    r_records = load_results(run_dir)
    
    # Common IDs
    common_ids = set(b_records.keys()).intersection(set(r_records.keys()))
    print(f"Found {len(common_ids)} common entries.")
    
    b_common = {k: b_records[k] for k in common_ids}
    r_common = {k: r_records[k] for k in common_ids}
    
    b_cd, b_f1, b_iou = print_metrics("Baseline", b_common)
    r_cd, r_f1, r_iou = print_metrics("Phase 2 Run", r_common)
    
    if b_cd and r_cd:
        print("\n=== DELTA (Run - Baseline) ===")
        cd_delta = np.median(r_cd) - np.median(b_cd)
        f1_delta = np.median(r_f1) - np.median(b_f1)
        iou_delta = np.median(r_iou) - np.median(b_iou)
        
        print(f"  CD Median Delta:  {cd_delta:+.4f} " + ("✅ (Lower is better)" if cd_delta < 0 else "❌"))
        print(f"  F1 Median Delta:  {f1_delta:+.4f} " + ("✅ (Higher is better)" if f1_delta > 0 else "❌"))
        print(f"  IoU Median Delta: {iou_delta:+.4f} " + ("✅ (Higher is better)" if iou_delta > 0 else "❌"))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, help="Directory containing baseline results.jsonl")
    parser.add_argument("--run", required=True, help="Directory containing run results.jsonl")
    args = parser.parse_args()
    
    compare(args.baseline, args.run)

if __name__ == "__main__":
    main()
