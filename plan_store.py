"""
plan_store.py — content-addressed persistence for accepted GeometryPlans.

Why this exists: fast-rlm is stateless across runs, but ForgeCAD's kernel is
deterministic — the same plan rebuilds the exact same solid. So the plan JSON is a
complete, replayable state object. Persisting it is what makes to-and-fro iteration
possible ("make the column taller") without re-deriving the design from scratch: an
edit run loads the prior plan, modifies it minimally, and re-verifies.

This is pure-Python, deterministic bookkeeping (hash + read/write JSON) — not a
bandage. It stores the source of truth (the plan), never the heavy solid, which is
rebuilt on demand.
"""

import json
import hashlib
import time
from pathlib import Path

STORE_DIR = Path(__file__).parent / "sessions"


def _store_dir():
    STORE_DIR.mkdir(exist_ok=True)
    return STORE_DIR


def plan_id(plan: dict) -> str:
    """Stable 12-char content hash of a plan (canonical JSON). Same plan -> same id."""
    blob = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


def _safe_label(label: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (label or "plan"))[:60]


def save_plan(plan: dict, label: str = None) -> dict:
    """Persist a plan. Returns {id, label, path, saved_at}. Latest pointer is updated."""
    d = _store_dir()
    pid = plan_id(plan)
    label = _safe_label(label or plan.get("title") or "plan")
    record = {"id": pid, "label": label, "saved_at": time.time(), "plan": plan}
    path = d / f"{label}__{pid}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    (d / "latest.txt").write_text(path.name, encoding="utf-8")
    return {"id": pid, "label": label, "path": str(path), "saved_at": record["saved_at"]}


def _resolve(ref: str) -> Path:
    d = _store_dir()
    if ref in (None, "", "latest"):
        ptr = d / "latest.txt"
        if not ptr.exists():
            raise FileNotFoundError("no saved plans yet")
        return d / ptr.read_text(encoding="utf-8").strip()
    cand = d / ref if ref.endswith(".json") else None
    if cand and cand.exists():
        return cand
    hits = [p for p in d.glob("*.json") if ref in p.name]   # match by id or label
    if not hits:
        raise FileNotFoundError(f"no saved plan matching {ref!r}")
    return sorted(hits, key=lambda p: p.stat().st_mtime)[-1]


def load_plan(ref: str = "latest") -> dict:
    """Load a stored plan by id, label, filename, or 'latest'. Returns the plan dict."""
    rec = json.loads(_resolve(ref).read_text(encoding="utf-8"))
    return rec["plan"]


def list_plans() -> list:
    """List stored plans (newest first): [{id,label,saved_at,title}]."""
    d = _store_dir()
    out = []
    for p in d.glob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
            out.append({"id": rec.get("id"), "label": rec.get("label"),
                        "saved_at": rec.get("saved_at"),
                        "title": (rec.get("plan") or {}).get("title")})
        except Exception:
            continue
    return sorted(out, key=lambda r: r.get("saved_at") or 0, reverse=True)
