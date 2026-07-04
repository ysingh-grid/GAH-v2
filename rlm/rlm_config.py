"""
Fast-RLM configuration with Gemini adapter
"""

import os
from dotenv import load_dotenv
from fast_rlm import RLMConfig

load_dotenv()

# Set required environment variables for Gemini's OpenAI compatibility endpoint
os.environ["RLM_MODEL_BASE_URL"] = "https://generativelanguage.googleapis.com/v1beta/openai/"
os.environ["RLM_MODEL_API_KEY"] = os.environ.get("GEMINI_API_KEY", "")

config = RLMConfig.default()
# Flash, not Pro. The planner is structured extraction (pick primitive, fill dims,
# emit JSON) — not a reasoning task. Billing is pay-as-you-go (Tier 1+), so RPM is
# NOT the constraint; flash is chosen for lower cost + 2-8s latency vs Pro's slower
# turns. (Free-tier RPM throttling does not apply on this account.)
# ROOT DRIVER = pro-tier thinking model. flash was a weak nondeterministic driver
# (13-40 turns for a box, over-delegated against instructions, same box swung
# 35k-498k tokens). A stronger coding model reasons more per turn → fewer turns →
# less of the quadratic prompt-token growth that dominated cost. Trade: pro spends
# more COMPLETION (reasoning) tokens per call, but prompt_tokens were the bloat.
# sub_agent (delegate_features children) stays flash for cost — separation of roles.
config.primary_agent = "gemini-3.1-pro-preview"
config.sub_agent = "gemini-3.5-flash"
# Hard safety-net cap on REPL steps per agent (the soft target lives in the prompt:
# root ~5-6 steps, leaf child ~3). Too low STARVES the root orchestrator — it needs
# probe + read-task + list_primitives + decompose + batch-fork + process + assemble
# + FINAL (~7-8 steps); hitting the cap before FINAL throws "Did not finish the
# function stack before subagent died". 8 was too tight. 12 gives the root margin.
# NOTE: this is NOT the token-balloon guard — max_depth=1 is (it stops the recursive
# grandchild fan-out). With depth capped, only ~6 agents exist, so a higher step cap
# does not re-balloon the cumulative token budget.
# Per-agent REPL step cap. With FLASH this couldn't go below ~50 (12 and 24 starved
# the complex container — "Did not finish the function stack before subagent died").
# Now paired with the pro-tier root driver, which reasons more per turn and should
# finish in far fewer turns, so 20 is the bet: bounds runaway AND should suffice for
# complex. If a complex part dies here, the pro driver still needs >20 turns — raise.
config.max_calls_per_subagent = 20
# max_prompt_tokens is a CUMULATIVE budget across all LLM calls in one run
# (not a per-call context limit). The fast-rlm default (200k) was calibrated
# for GPT-4 class models. Gemini Flash has a 1M token context window; our
# planner is the only agent and a typical run burns ~150-220k tokens across
# 6 REPL steps (system prompt × N + growing history + skill reads + web search
# answers). Raising to 400k gives comfortable headroom without approaching the
# model's actual window limit.
config.max_prompt_tokens = 1_000_000
# max_completion_tokens is the cumulative COMPLETION (reasoning + output) budget
# across the run. RLMConfig.default() is 50_000 — calibrated for GPT-4-class,
# NON-thinking models. Our root is now gemini-3.1-pro-preview, a THINKING model
# that spends reasoning tokens on every turn; leaving the 50k default lets a
# complex part exhaust the budget mid-reason and die. Own it explicitly at 150k
# (matches the reference run.yaml) so the pro driver has room to finish.
config.max_completion_tokens = int(os.environ.get("RLM_MAX_COMPLETION_TOKENS", "150000"))
# max_money_spent is the hard USD cap for the whole run. RLMConfig.default() is
# 0.2 — 5x tighter than we want and never a deliberate choice here; a complex
# container run brushes it and gets force-stopped short. Own it at 1.00 (matches
# the reference run.yaml). Lower via RLM_MAX_MONEY for cost-bounded eval sweeps.
config.max_money_spent = float(os.environ.get("RLM_MAX_MONEY", "1.00"))
# truncate_len controls how many chars of REPL stdout the engine shows back to
# the model after each execution step. The default (2000) is too short for our
# skills. When truncated, the model compensates by manually printing the next
# slice (e.g. playbook[2000:4000]) in the next step — wasting a whole step + its
# growing-history overhead just to read content it already fetched. Sized so the
# LONGEST skill fits in one REPL output with headroom (playbook.md is 8,025 chars
# as of 2026-07; the previous 8000 silently truncated it and re-triggered the
# exact pagination problem this knob was raised to eliminate). A test guards
# skills/*.md staying under this value.
config.truncate_len = 12000
# max_depth caps llm_query() recursion. The engine makes an agent at depth ==
# max_depth a LEAF: its llm_query is removed and any fork attempt throws. So
# max_depth=1 means root planner (depth 0) forks ONE level of sub-part agents
# (depth 1), and those children are LEAVES — they cannot fork grandchildren.
# This is the hard, engine-level enforcement of strict 1-to-1 fork-and-return;
# without it (default 3, or even 2) children recursively fork and the cumulative
# prompt-token budget explodes (observed 459k tokens from a depth-2 fan-out).
config.max_depth = 1
# ── LLM call resilience ───────────────────────────────────────────────────────
# api_timeout_ms + api_max_retries flow to the TS LLM client (call_llm.ts) via the
# --config temp YAML that _runner.run() writes from this RLMConfig. The engine's
# bundled rlm_config.yaml defaults to 30000ms / 3 retries; we set them explicitly
# here so the values are owned in code, not silently inherited.
#
# The planner can send large-context calls after reading skills/primitive specs.
# A 30s per-attempt timeout killed valid Gemini calls before Temporal could start
# the workflow, leaving the UI with an empty workflow list. Give each attempt
# enough room to finish, but keep retries modest so a real outage still returns.
config.api_timeout_ms = int(os.environ.get("RLM_API_TIMEOUT_MS", "120000"))
config.api_max_retries = int(os.environ.get("RLM_API_MAX_RETRIES", "2"))

# ── Compression guard ──────────────────────────────────────────────────────────
# Default forces a self-confirm (same model, same system prompt) + compress+retry
# before a delegate_features call with a large, barely-compressed context runs.
# Explicitly off: no compression step, no extra confirm call before a fork.
config.enable_compression_guard = False

# ── Generation params (temperature / seed / top_p) ────────────────────────────
# NOT RLMConfig fields — fast_rlm.run() takes these via its `llm_kwargs=` arg and
# spreads them UNTOUCHED into every chat.completions.create call (root + all
# sub-agents). RLMConfig has no temperature/seed, so this is the ONLY channel;
# with llm_kwargs unset the provider's own default temperature (~1.0) applies,
# which is wrong for a structured-extraction planner.
#
# temperature: the planner picks a primitive, fills dims, emits JSON — extraction,
#   not open reasoning. Low temp = stable, repeatable plans. 0.0 is rejected by
#   some Gemini routes; 0.1 is the safe floor.
# seed: BEST-EFFORT. OpenAI honors it (+ returns system_fingerprint); Gemini's
#   OpenAI-compat endpoint MAY ignore it — set it to ATTEMPT repro, do NOT expect
#   bit-identical runs. Enable by exporting RLM_SEED; unset = normal production.
LLM_KWARGS: dict = {
    "temperature": float(os.environ.get("RLM_TEMPERATURE", "0.1")),
    "top_p": float(os.environ.get("RLM_TOP_P", "0.95")),
}
_seed = os.environ.get("RLM_SEED")
if _seed not in (None, ""):
    LLM_KWARGS["seed"] = int(_seed)


def _audit_inherited_defaults(cfg) -> list[str]:
    """Make the fallback to RLMConfig.default() LOUD, not silent.

    Every RLMConfig field we do not explicitly OWN below keeps its
    RLMConfig.default() value — defaults calibrated for GPT-4-class models that
    are often wrong for our Gemini pro/flash split (the 50k completion cap + 0.2
    money cap were exactly this). This prints which fields are OWNED vs INHERITED
    at import time so an inherited default can never silently degrade a run.
    Returns the list of inherited field names (also usable in tests)."""
    import dataclasses

    # Fields this module deliberately sets. Keep in sync with the assignments above.
    owned = {
        "primary_agent", "sub_agent", "max_depth", "max_calls_per_subagent",
        "max_prompt_tokens", "max_completion_tokens", "max_money_spent",
        "truncate_len", "api_timeout_ms", "api_max_retries",
        "enable_compression_guard",
    }
    defaults = RLMConfig.default()
    inherited = []
    for f in dataclasses.fields(cfg):
        if f.name in owned:
            continue
        if getattr(cfg, f.name) == getattr(defaults, f.name):
            inherited.append(f.name)
    if inherited:
        print(
            "⚠️  RLM Config — fields INHERITED from RLMConfig.default() (not owned "
            "here; verify they suit the current models):"
        )
        for name in inherited:
            print(f"      {name} = {getattr(cfg, name)!r}  [default]")
    return inherited


print("✅ RLM Config created with Gemini adapter")
print(f"   owned budgets: max_completion_tokens={config.max_completion_tokens}, "
      f"max_money_spent={config.max_money_spent}, max_prompt_tokens={config.max_prompt_tokens}")
print(f"   generation params (llm_kwargs): {LLM_KWARGS}")
_audit_inherited_defaults(config)
