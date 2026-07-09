"""Data access for the approved-designs store (the trace flywheel).

The ONLY place that reads/writes data/approved_designs.json. Writes are
concurrency-safe (module lock + atomic replace) and idempotent by run_id, so
approving the same run twice — or two sessions approving at once — never corrupts
or duplicates. Reads are tolerant of a missing/corrupt file (degrade to empty)
so a bad store can never break the planner's reference retrieval.

Mirrors the index/fetch shape of backend/kb_read so approved designs merge into
the design-reference index alongside curated recipes:
  index_approved()   → {approved__<run_id>: prompt}   — the menu
  fetch_approved([]) → {key: {description, steps}}     — the content by key
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# store.py -> approved_store -> backend -> repo root, then /data.
_APPROVED_PATH = Path(__file__).resolve().parents[2] / "data" / "approved_designs.json"

_KEY_PREFIX = "approved__"     # index/fetch key namespace for approved runs
MAX_APPROVED = 500             # hard cap on stored entries (trim oldest beyond)
MAX_INDEX = 30                 # most-recent entries surfaced in the index
_NEAR_DUP_KEYWORDS = 4         # shared-keyword threshold for the soft dup guard

# Serialises the read-modify-write in append_approved. The file I/O runs in a
# thread-pool executor (async handler), so a threading.Lock is the right guard.
_LOCK = threading.Lock()

# Generic tokens that carry no retrieval signal — dropped from derived keywords
# so two unrelated parts don't match on "design"/"make"/units.
_STOP_WORDS = {
    "a", "an", "the", "of", "for", "and", "with", "to", "in", "on", "at", "by",
    "mm", "cm", "that", "this", "it", "is", "be", "design", "make", "create",
    "model", "part", "generate", "please", "want", "need",
}


def _load() -> dict:
    """Load the store document; tolerant of a missing OR corrupt file → empty.

    A decode error (e.g. a truncated write from a crashed process) degrades to an
    empty store rather than raising, so a bad file never breaks the planner's
    lookup path — worst case, retrieval sees no approved designs.
    """
    try:
        with _APPROVED_PATH.open(encoding="utf-8") as f:
            doc = json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {"approved": []}
    if not isinstance(doc, dict) or not isinstance(doc.get("approved"), list):
        return {"approved": []}
    return doc


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tokens(text: str) -> list[str]:
    return [w.strip(".,/()[]{}\"'-").lower() for w in text.split()]


def _derive_keywords(prompt: str, plan: dict[str, Any]) -> list[str]:
    """Retrieval keys for an approved design: prompt + part_name tokens, minus
    stop-words and bare numbers, order-preserving deduped."""
    words = _tokens(prompt or "")
    part = str(plan.get("part_name") or "")
    words += _tokens(part.replace("_", " "))
    out: list[str] = []
    for w in words:
        if w and w not in _STOP_WORDS and not w.isdigit() and w not in out:
            out.append(w)
    return out


def _key_for(run_id: str) -> str:
    return f"{_KEY_PREFIX}{run_id}"


def _atomic_write(doc: dict) -> None:
    """Write via a temp file + os.replace so a crash mid-write can't corrupt the
    store (readers always see the whole old or whole new file)."""
    _APPROVED_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _APPROVED_PATH.with_name(_APPROVED_PATH.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    os.replace(tmp, _APPROVED_PATH)


def append_approved(
    *,
    run_id: str,
    original_prompt: str,
    plan: dict[str, Any],
    intake_context: str = "",
    feature_checklist: str = "",
) -> dict:
    """Persist one user-approved design. Concurrency-safe, idempotent by run_id.

    Returns {"status": ..., "run_id": run_id} where status is:
      "approved"         — stored a new entry
      "already_approved" — run_id already present (no-op)
      "duplicate"        — a near-identical recent design already exists (no-op)
      "skipped"          — missing run_id or an empty/invalid plan (no-op)
    """
    if not run_id or not isinstance(plan, dict) or not plan.get("steps"):
        return {"status": "skipped", "run_id": run_id}

    with _LOCK:
        doc = _load()
        entries: list[dict] = doc["approved"]

        if any(e.get("run_id") == run_id for e in entries):
            return {"status": "already_approved", "run_id": run_id}

        keywords = _derive_keywords(original_prompt, plan)
        part = str(plan.get("part_name") or "")
        kset = set(keywords)
        # Soft near-dup guard: same part_name AND heavy keyword overlap with a
        # recent entry → skip, so 20 approvals of the same flange don't crowd
        # retrieval. run_id idempotency above is the hard dedup.
        for e in entries[-20:]:
            if e.get("part_name") == part and len(kset & set(e.get("keywords", []))) >= _NEAR_DUP_KEYWORDS:
                return {"status": "duplicate", "run_id": run_id}

        entries.append(
            {
                "run_id": run_id,
                "timestamp": _now(),
                "original_prompt": original_prompt,
                "intake_context": intake_context,
                "feature_checklist": feature_checklist,
                "part_name": part,
                "keywords": keywords,
                "plan": plan,
            }
        )
        if len(entries) > MAX_APPROVED:
            del entries[: len(entries) - MAX_APPROVED]  # drop oldest
        _atomic_write(doc)

    return {"status": "approved", "run_id": run_id}


def index_approved(limit: int | None = None) -> dict[str, str]:
    """Compact menu of the newest approved designs: {approved__<run_id>: prompt}.

    Newest first, capped at `limit` (default MAX_INDEX, resolved at call time) so
    the index stays token-cheap as the store grows. Descriptions are the original
    prompt so the planner can pick relevant keys, then fetch only those.
    """
    limit = MAX_INDEX if limit is None else limit
    entries = _load()["approved"]
    out: dict[str, str] = {}
    for e in reversed(entries[-limit:]):
        out[_key_for(str(e.get("run_id", "")))] = str(e.get("original_prompt", ""))[:140]
    return out


def fetch_approved(keys: list[str]) -> dict[str, dict]:
    """Fetch approved designs by their approved__* keys (from index_approved()).

    Non-approved keys are ignored (the caller mixes recipe/fastener keys in).
    Returns {key: {description, original_prompt, steps}} — same adaptable-steps
    shape a curated recipe exposes.
    """
    wanted = {k for k in keys if k.startswith(_KEY_PREFIX)}
    if not wanted:
        return {}
    out: dict[str, dict] = {}
    for e in _load()["approved"]:
        key = _key_for(str(e.get("run_id", "")))
        if key in wanted:
            out[key] = {
                "description": f"Approved past design: {e.get('original_prompt', '')}",
                "original_prompt": e.get("original_prompt", ""),
                "steps": (e.get("plan") or {}).get("steps", []),
            }
    return out
