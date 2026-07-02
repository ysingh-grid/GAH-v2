"""Sequential pipeline runner for the dataset_v2 corpus.

Runs each prompt in dataset_v2/{t1,t2,t3}.jsonl through the FULL agent pipeline
(planner -> geometry loop) in tier order, logging per test:

  - last stage reached + status (success / failed / plan_error / exception)
  - WHERE it broke: failure_category + failure_detail (or exception traceback)
  - the produced STL path "all the way" (outputs/<id>/solid.stl[_repaired]) + size
  - the trace.json path (full last state) and attempt count

Resumable: ids already in results.jsonl are skipped. Each test flushes
immediately so a crash mid-run keeps the partial log.

Run (needs backend up on :8001, deno, GEMINI_API_KEY, meshlib+cadquery):
    .venv/bin/python -m eval.run_dataset_v2 --backend-url http://localhost:8001
    .venv/bin/python -m eval.run_dataset_v2 --limit 2          # smoke: 2 per tier
    .venv/bin/python -m eval.run_dataset_v2 --tiers t1         # one tier only
"""

from __future__ import annotations

import argparse
import json
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
_DATASET = _REPO / "dataset_v2"
_TIER_FILES = {
    "t1": "t1_primitives.jsonl",
    "t2": "t2_engineering_parts.jsonl",
    "t3": "t3_complex_parts.jsonl",
}


def _load_tests(tiers: list[str]) -> list[dict[str, Any]]:
    """Load test records for the requested tiers, in tier then file order."""
    tests: list[dict[str, Any]] = []
    for tier in tiers:
        path = _DATASET / _TIER_FILES[tier]
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    tests.append(json.loads(line))
    return tests


def _done_ids(results_path: Path) -> set[str]:
    """Ids already logged in a prior (interrupted) run — skipped on resume."""
    if not results_path.exists():
        return set()
    done: set[str] = set()
    with results_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                done.add(json.loads(line)["id"])
    return done


def _stl_record(run_id: str) -> dict[str, Any]:
    """Locate the produced STL for a run and report path + size."""
    from tools.artifacts import run_dir

    d = run_dir(run_id)
    # repaired wins if present (it is what the loop carried forward)
    for name in ("solid_repaired.stl", "solid.stl"):
        p = d / name
        if p.exists():
            return {"stl_path": str(p), "stl_exists": True, "stl_bytes": p.stat().st_size}
    return {"stl_path": str(d / "solid.stl"), "stl_exists": False, "stl_bytes": None}


def _inspect_geom(stl_path: str | None) -> dict[str, Any] | None:
    """Return {volume, bbox} for an STL via MeshLib, or None if unreadable."""
    if not stl_path or not Path(stl_path).exists():
        return None
    from tools.inspect_mesh import inspect_mesh

    r = inspect_mesh(stl_path)
    if not r.get("success"):
        return None
    return {"volume": r.get("volume_mm3"), "bbox": r.get("bbox")}


def _bbox_dims(b: dict[str, float]) -> tuple[float, float, float]:
    """X/Y/Z extents of a bbox dict."""
    return (b["xmax"] - b["xmin"], b["ymax"] - b["ymin"], b["zmax"] - b["zmin"])


def _attach_code_and_compare(rec: dict[str, Any], test: dict[str, Any], out_dir: Path) -> None:
    """Save produced CQ + reference CQ, and geometrically compare produced vs reference STL.

    "Compare CQ code" = compare the GEOMETRY each CadQuery produces (text diff of
    code is noise — different style, same shape). We inspect the produced STL and
    the dataset's reference STL with MeshLib and report volume ratio + bbox delta.
    """
    tid = test["id"]
    code_dir = out_dir / "code"
    code_dir.mkdir(exist_ok=True)

    # reference CadQuery (dataset ground truth)
    ref_code = test.get("reference_code", "")
    ref_cq_path = code_dir / f"{tid}.reference.cq.py"
    ref_cq_path.write_text(ref_code, encoding="utf-8")
    rec["reference_cq_path"] = str(ref_cq_path)

    # produced CadQuery (read from the trace the loop wrote)
    produced_cq: str | None = None
    if rec.get("trace_path") and Path(rec["trace_path"]).exists():
        try:
            tr = json.loads(Path(rec["trace_path"]).read_text(encoding="utf-8"))
            produced_cq = tr.get("code")
        except (json.JSONDecodeError, OSError):
            produced_cq = None
    if produced_cq:
        prod_cq_path = code_dir / f"{tid}.produced.cq.py"
        prod_cq_path.write_text(produced_cq, encoding="utf-8")
        rec["produced_cq_path"] = str(prod_cq_path)

    # geometric comparison: produced STL vs reference STL (both via MeshLib)
    ref_stl = _DATASET / "reference_stls" / f"{tid}.stl"
    prod = _inspect_geom(rec.get("stl_path"))
    ref = _inspect_geom(str(ref_stl)) if ref_stl.exists() else None
    cmp: dict[str, Any] = {"ref_stl_exists": ref_stl.exists()}
    if prod and ref and ref.get("volume"):
        vr = prod["volume"] / ref["volume"]
        pd, rd = _bbox_dims(prod["bbox"]), _bbox_dims(ref["bbox"])
        bbox_delta = [round(p - r, 2) for p, r in zip(pd, rd, strict=True)]
        cmp.update(
            ref_volume_mm3=round(ref["volume"], 1),
            prod_volume_mm3=round(prod["volume"], 1),
            volume_ratio=round(vr, 3),
            bbox_delta_mm=bbox_delta,
            geom_match=bool(0.9 <= vr <= 1.1 and all(abs(d) <= 1.0 for d in bbox_delta)),
        )
    rec["cq_compare"] = cmp


def _run_one(test: dict[str, Any], *, backend_url: str, verify: bool, out_dir: Path) -> dict[str, Any]:
    """Run one prompt through planner -> loop; return a flat result record."""
    from runtime.planner import run_planner_turn, run_replanner_turn
    from runtime.schema import load_library
    from runtime.loop import run_geometry_loop

    test_id = test["id"]
    prompt = test["prompt"]
    started = time.monotonic()
    rec: dict[str, Any] = {
        "id": test_id,
        "tier": test.get("tier"),
        "prompt": prompt,
        "ts": datetime.now(UTC).isoformat(),
        "status": None,
        "last_stage": "planning",
        "failure_category": None,
        "failure_detail": None,
        "attempts": 0,
        "run_id": test_id,
        "stl_path": None,
        "stl_exists": False,
        "stl_bytes": None,
        "trace_path": None,
        "forge_js_bytes": 0,
        "forge_js_path": None,
        "produced_cq_path": None,
        "reference_cq_path": None,
        "cq_compare": None,
        "error": None,
    }
    try:
        plan = run_planner_turn(prompt, [], backend_url=backend_url)

        def planner_fn(original_prompt: str, history: list[dict[str, str]]):  # noqa: ANN202
            return run_replanner_turn(original_prompt, history, backend_url=backend_url)

        result = run_geometry_loop(
            original_prompt=prompt,
            initial_plan=plan,
            planner_fn=planner_fn,
            library=load_library(),
            run_id=test_id,
            verify=verify,
        )
        rec.update(
            status=result.status,
            attempts=result.attempts,
            failure_category=result.failure_category,
            failure_detail=result.message,
            trace_path=result.trace_path,
            forge_js_bytes=len(result.forge_js or ""),
            last_stage="done" if result.status == "success" else "geometry/verify",
        )
        rec.update(_stl_record(test_id))
        if result.forge_js:
            forge_path = out_dir / "code" / f"{test_id}.forge.js"
            forge_path.parent.mkdir(exist_ok=True)
            forge_path.write_text(result.forge_js, encoding="utf-8")
            rec["forge_js_path"] = str(forge_path)
    except Exception:  # noqa: BLE001 — capture ANY failure as a logged result, never abort the suite
        rec["status"] = "exception"
        rec["error"] = traceback.format_exc()[-2000:]
        rec.update(_stl_record(test_id))  # an STL may exist even if a later stage threw
    finally:
        rec["elapsed_s"] = round(time.monotonic() - started, 1)
    # code capture + geometric compare vs reference (best-effort, never fatal)
    try:
        _attach_code_and_compare(rec, test, out_dir)
    except Exception:  # noqa: BLE001
        rec.setdefault("cq_compare", {})["compare_error"] = traceback.format_exc()[-400:]
    return rec


def _fmt_line(rec: dict[str, Any]) -> str:
    """One human-readable log line summarising a test outcome."""
    flag = {"success": "PASS", "failed": "FAIL",
            "exception": "ERR "}.get(rec["status"] or "", "????")
    stl = f"stl={rec['stl_bytes']}B" if rec["stl_exists"] else "stl=NONE"
    where = rec["failure_category"] or rec["last_stage"]
    cmp = rec.get("cq_compare") or {}
    if "geom_match" in cmp:
        comp = f"vsREF={'MATCH' if cmp['geom_match'] else 'DIFF'}(vr={cmp.get('volume_ratio')})"
    else:
        comp = "vsREF=n/a"
    return (f"[{flag}] {rec['id']:<7} {rec['elapsed_s']:>5}s  {stl:<11} {comp:<22} "
            f"stage={where:<18} {(rec['failure_detail'] or '')[:70]}")


def main() -> None:
    """CLI entry: run the corpus sequentially, logging each result."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend-url", default="http://localhost:8001")
    ap.add_argument("--tiers", default="t1,t2,t3", help="comma list, run in this order")
    ap.add_argument("--limit", type=int, default=0, help="max tests PER TIER (0 = all)")
    ap.add_argument("--no-verify", action="store_true", help="skip the multimodal verifier")
    ap.add_argument("--out", default="", help="output dir (default eval_results/dataset_v2/<ts>)")
    args = ap.parse_args()

    tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]
    out_dir = Path(args.out) if args.out else (
        _REPO / "eval_results" / "dataset_v2" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    log_path = out_dir / "run.log"

    tests = _load_tests(tiers)
    if args.limit:
        per_tier: dict[str, int] = {}
        capped = []
        for t in tests:
            tier = t.get("tier", "?")
            if per_tier.get(tier, 0) < args.limit:
                capped.append(t)
                per_tier[tier] = per_tier.get(tier, 0) + 1
        tests = capped

    done = _done_ids(results_path)
    print(f"Running {len(tests)} tests -> {out_dir}  (skipping {len(done)} done)")

    counts: dict[str, int] = {}
    for i, test in enumerate(tests, 1):
        if test["id"] in done:
            continue
        rec = _run_one(test, backend_url=args.backend_url, verify=not args.no_verify, out_dir=out_dir)
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
        with results_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        line = f"{i:>3}/{len(tests)} " + _fmt_line(rec)
        print(line)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    summary = {"total": len(tests), "by_status": counts, "out_dir": str(out_dir)}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\nSUMMARY:", json.dumps(counts))
    print("Results:", results_path)


if __name__ == "__main__":
    main()
