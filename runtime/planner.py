"""Per-turn RLM planner: one user message in, one validated PrimitivePlan out.

The backend re-invokes `run_planner_turn` on every user message with the full
chat history. The RLM must always resolve the request to a validated
PrimitivePlan — there is no clarifying-question escape hatch; ambiguity gets
resolved with reasonable defaults, not punted back to the user. output_schema
is the PrimitivePlan itself, so the model's FINAL is schema-checked (and
self-corrected on mismatch) by fast-rlm before we ever see it.

This module owns the *pure* pieces (the output contract, the task prompt, the
result parser). The single impure call — `fast_rlm.run` — is isolated in
`run_planner_turn` so everything else is unit-testable without network or cost.

Callers must handle exceptions: run_planner_turn/run_replanner_turn raise on
unrecoverable failure (budget exhausted, no FINAL emitted, a schema mismatch
fast-rlm's own retry loop couldn't resolve) instead of masking it as a fake
user-facing question.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)


def _llm_kwargs() -> dict:
    """Generation params (temperature/seed/top_p) for every fast_rlm.run call.

    Lazy import keeps this module import-safe without rlm_config (mirrors how
    `config` is lazily imported below). fast_rlm.run spreads these into every
    chat.completions.create call, so setting them once per run() covers the
    whole (now single-agent, no-fork) planner."""
    from rlm.rlm_config import LLM_KWARGS

    return LLM_KWARGS


# Tools the planner may call inside its REPL. Imported as objects so fast-rlm
# can extract their source; they must stay self-contained (see rlm/pull_tools).
from rlm.pull_tools import (
    fetch_design_reference,
    fetch_kb_sections,
    list_design_reference_index,
    list_kb_index,
    list_primitives,
    list_skills,
    list_skills_replan,
    lookup_primitive,
    read_skill,
)
from runtime.schema import PrimitivePlan

if TYPE_CHECKING:
    from fast_rlm import RLMConfig

_PLANNER_TOOLS = [
    read_skill,
    list_skills,
    list_primitives,
    lookup_primitive,
    list_kb_index,
    fetch_kb_sections,
    list_design_reference_index,
    fetch_design_reference,
]
# NO child-delegation tools. Both were removed after measurement:
#   - delegate_stage (per-stage fork) — pure overhead over tiny per-stage context;
#     drove a single solid to >1M tokens / runaway.
#   - delegate_features (per-solid fork for assemblies) — NO token benefit
#     (pure-inline box still ~183k/17 steps) AND never once invoked across logged
#     runs; the planner always planned inline / via patterns. The real cost was
#     the monolithic root's per-step context growth + flash's step count, not the
#     lack of delegation. The planner is now a flat, single-agent inline planner.

_REPLANNER_TOOLS = [
    read_skill,
    list_skills_replan,
    list_primitives,
    lookup_primitive,
    list_kb_index,
    fetch_kb_sections,
    list_design_reference_index,
    fetch_design_reference,
]
# list_skills_replan (NOT list_skills): the replanner discovers ONLY its own
# scoped guide catalog (SKILLS_replan.md) — it never sees the planner-only
# intake/decomposition/verification guides. read_skill stays shared (access is
# open, discovery is scoped), so a guide listed in both catalogs still resolves.
# If you add a new tool to _PLANNER_TOOLS, it does NOT automatically appear here
# — add it explicitly only if the replanner genuinely needs it.


def parse_planner_result(result: Any) -> PrimitivePlan:
    """Validate a fast-rlm FINAL dict into a PrimitivePlan (raises on mismatch)."""
    if isinstance(result, PrimitivePlan):
        return result
    return PrimitivePlan.model_validate(result)


PLANNER_TASK = """\
You are the PLANNER. Turn the user's request (original_prompt, plus any
chat_history) into ONE validated PrimitivePlan.

Everything you need for a typical part is ALREADY IN CONTEXT — do not spend
REPL steps re-fetching it:
- context["skills"]["playbook"] — your operating guide (steps, output contract)
- context["available_primitives"] — {name: one-line signature with parameters}
- context["reference_index"] — {key: description} menu of proven recipes and
  past user-approved designs; fetch a key's full steps only when one matches.

Aim to emit FINAL in your FIRST repl block: read the context, follow the
playbook's order of thought inline, and FINAL the plan. Use tools only for
what is genuinely missing (full spec of an unusual primitive, a KB section,
fetching a matching reference by key). Resolve ambiguity with reasonable
defaults; there is no option to ask the user.
"""


# skills/ ships alongside runtime/ in both the repo and the docker image —
# resolve relative to this file, never the CWD.
_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


def _skill_content(name: str) -> str | None:
    """Read one skill's markdown from disk for context pre-injection.

    Pre-injecting the playbook saves the 2 REPL turns every run was measured
    to burn on fetching + printing it — each turn re-sends the whole growing
    transcript AND is one more exposure to a provider stall (measured stalls:
    50-250s per call). Returns None on any failure: the pull tools still
    exist, so the planner degrades to fetching on demand, never breaks.
    """
    try:
        return (_SKILLS_DIR / f"{name}.md").read_text(encoding="utf-8")
    except Exception:
        return None


def _primitive_signatures() -> dict[str, str] | None:
    """Compact {name: signature} catalog for context pre-injection.

    One line per primitive: description + parameter names/types/defaults.
    ~0.7k tokens for the whole catalog — cheaper than even ONE
    growing-transcript lookup turn, and it removes the main reason plans
    hallucinate parameter names (the model guesses when it decides a lookup
    turn isn't worth it). Full specs (per-parameter descriptions, constraints)
    stay pull-only for the unusual primitives that need them.
    """
    try:
        from runtime import schema

        library = schema.load_library()
        catalog: dict[str, str] = {}
        for name, spec in library.items():
            params = spec.get("parameters", {}) or {}
            sig = ", ".join(
                f"{p}:{(meta or {}).get('type', '?')}"
                + (f"={meta['default']}" if isinstance(meta, dict) and "default" in meta else "")
                for p, meta in params.items()
            )
            desc = str(spec.get("description", "")).split(". ")[0].strip()
            catalog[name] = f"{desc} — params: {sig}" if sig else desc
        return catalog or None
    except Exception:
        return None


def _reference_index() -> dict[str, str] | None:
    """Pre-fetch the design-reference index (recipes + approved past designs).

    Same host-side pre-fetch pattern as list_primitives: the menu is tiny
    (one line per key) and having it VISIBLE in context makes the planner
    actually consider approved designs instead of needing a discovery turn
    first. Content stays fetch-by-key. None on failure — the tool remains.
    """
    try:
        return list_design_reference_index()
    except Exception:
        return None


def build_planner_query(
    original_prompt: str,
    chat_history: list[dict[str, str]],
    *,
    available_primitives: list[str] | dict[str, str] | None = None,
    skills: dict[str, str] | None = None,
    reference_index: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Assemble the structured context dict handed to the RLM for one turn.

    Pre-inject everything a TYPICAL run needs; keep the LARGE/rare data
    pull-by-reference. Rationale, all measured live: every extra REPL turn
    re-sends the whole growing transcript (quadratic cost; removing even the
    tiny primitives menu pushed a complex part 326k → 464k tokens) AND is one
    more LLM call that can hit a provider stall (50-250s spikes measured).
    Runs were burning 4-7 turns fetching the playbook, primitive specs, and
    the reference index before doing any actual planning — those three now
    ride in context, aiming the planner at FINAL-in-one-block:
      - available_primitives: {name: one-line signature} (~0.7k tokens)
      - skills["playbook"]: the full operating guide (~2.6k tokens)
      - reference_index: {key: description} incl. approved past designs
    Full primitive specs and KB sections stay pull-only via the tools. Every
    field degrades gracefully: None → omitted → the planner falls back to its
    pull tools (whose docstrings carry the same guidance).
    """
    # task = the planner's standing instruction; the user's actual request lives
    # ONLY in original_prompt/chat_history. (task used to duplicate original_prompt
    # byte-for-byte — pure wasted context on every REPL step.)
    query: dict[str, Any] = {
        "task": PLANNER_TASK,
        "original_prompt": original_prompt,
        "chat_history": chat_history,
    }
    if available_primitives is not None:
        query["available_primitives"] = available_primitives
    if skills:
        query["skills"] = skills
    if reference_index:
        query["reference_index"] = reference_index
    return query


def run_planner_turn(
    original_prompt: str,
    chat_history: list[dict[str, str]],
    *,
    backend_url: str,
    config: RLMConfig | None = None,
) -> PrimitivePlan:
    """Run one planner turn against the RLM and return its validated plan.

    Args:
        original_prompt: The user's first request.
        chat_history: Prior turns as [{"role": "user"|"planner", "content": str}].
        backend_url: Base URL of the product backend, injected into the REPL as
            DTCM_BACKEND_URL so the pull tools can reach it.
        config: Optional fast-rlm RLMConfig; defaults to rlm.rlm_config.config.

    Returns:
        A validated PrimitivePlan.

    Raises:
        Whatever fast-rlm/parse_planner_result raise on unrecoverable failure
        (budget exhaustion, no FINAL emitted, a schema mismatch the engine's own
        retry loop couldn't resolve). Callers must handle this — there is no
        graceful ask_user fallback here.
    """
    import os

    import fast_rlm

    if config is None:
        from rlm.rlm_config import config as default_config

        config = default_config

    # Host-side pre-fetch of everything a typical run needs (see
    # build_planner_query for the measured rationale): compact primitive
    # signatures from the library on disk, the playbook from skills/ on disk,
    # and the reference index over HTTP. The pull tools read DTCM_BACKEND_URL
    # from the env, so set it before the pre-fetch. kb_index stays pull-only
    # (a supplementary CadQuery-API menu the planner rarely needs).
    os.environ["DTCM_BACKEND_URL"] = backend_url
    available_primitives = _primitive_signatures()
    if available_primitives is None:
        try:
            available_primitives = list_primitives()
        except Exception:
            available_primitives = None
    playbook = _skill_content("playbook")

    result = fast_rlm.run(
        build_planner_query(
            original_prompt,
            chat_history,
            available_primitives=available_primitives,
            skills={"playbook": playbook} if playbook else None,
            reference_index=_reference_index(),
        ),
        config=config,
        tools=_PLANNER_TOOLS,
        output_schema=PrimitivePlan,
        env_variables={
            "DTCM_BACKEND_URL": backend_url,
        },
        llm_kwargs=_llm_kwargs(),
    )
    return parse_planner_result(result["results"])


REPLANNER_TASK = """\
You are the REPLANNER. A plan already exists and needs ONE revision — the request
is in the last message of chat_history, along with the current plan.

Your guides are ALREADY IN CONTEXT — do not spend REPL steps re-fetching them:
- context["skills"]["playbook_replan"] — your steps and output contract
- context["skills"]["repair_guidance"] / ["refinement_guidance"] — the fix
  guides; the failure message names which one matches
- context["available_primitives"] — {name: one-line signature with parameters}

Aim to emit FINAL in your FIRST repl block: read the failure detail and the
matching guide from context, change only what the failure calls for, keep every
other step unchanged, and FINAL the corrected plan.
"""


def run_replanner_turn(
    original_prompt: str,
    chat_history: list[dict[str, str]],
    *,
    backend_url: str | None = None,
    config: RLMConfig | None = None,
) -> PrimitivePlan:
    """Run one replan turn against the scoped replanner toolset (no fork tool).

    Args:
        original_prompt: The user's original request.
        chat_history: Prior turns plus the trailing feedback/edit system message
            (see runtime.replan.replan_with_feedback).
        backend_url: Base URL of the product backend, injected into the REPL as
            DTCM_BACKEND_URL so the read-only pull tools can reach it.
        config: Optional fast-rlm RLMConfig; defaults to rlm.rlm_config.config.

    Returns:
        A validated, corrected PrimitivePlan.

    Raises:
        Same as run_planner_turn — no graceful ask_user fallback. Callers
        (replan_activity / the in-process loop) handle the failure explicitly.
    """
    import os

    import fast_rlm

    if config is None:
        from rlm.rlm_config import config as default_config
        config = default_config

    if backend_url:
        os.environ["DTCM_BACKEND_URL"] = backend_url

    # Pre-inject what every replan needs (same measured rationale as the
    # planner: each avoided REPL turn skips a whole growing-transcript resend
    # AND one more stall-exposed LLM call). Replans were burning 3-5 turns
    # fetching playbook_replan + the stage guidance before touching the plan.
    # BOTH guidance files ride along (repair ~4k chars, refinement ~3k) rather
    # than threading the failure stage through here — the feedback message
    # names which one applies. kb_index stays pull-only.
    available_primitives = _primitive_signatures()
    if available_primitives is None and backend_url:
        try:
            available_primitives = list_primitives()
        except Exception:
            available_primitives = None
    skills = {
        name: content
        for name in ("playbook_replan", "repair_guidance", "refinement_guidance")
        if (content := _skill_content(name))
    }

    query: dict[str, Any] = {
        "task": REPLANNER_TASK,
        "original_prompt": original_prompt,
        "chat_history": chat_history,
    }
    if available_primitives is not None:
        query["available_primitives"] = available_primitives
    if skills:
        query["skills"] = skills
    result = fast_rlm.run(
        query,
        config=config,
        tools=_REPLANNER_TOOLS,
        output_schema=PrimitivePlan,
        env_variables={
            "DTCM_BACKEND_URL": backend_url or "",
        },
        llm_kwargs=_llm_kwargs(),
    )
    return parse_planner_result(result["results"])
