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
# emit JSON) — not a reasoning task. Pro had 2 RPM free-tier rate limit, causing
# 90s queue spikes that blew the 30s timeout. Flash has 15 RPM + 2-8s latency.
config.primary_agent = "gemini-3.5-flash"
config.sub_agent = "gemini-3.5-flash"
# PRD gate: <5m per single-part workflow. Cap tool calls to force tight paths.
config.max_calls_per_subagent = 20
# max_prompt_tokens is a CUMULATIVE budget across all LLM calls in one run
# (not a per-call context limit). The fast-rlm default (200k) was calibrated
# for GPT-4 class models. Gemini Flash has a 1M token context window; our
# planner is the only agent and a typical run burns ~150-220k tokens across
# 6 REPL steps (system prompt × N + growing history + skill reads + web search
# answers). Raising to 400k gives comfortable headroom without approaching the
# model's actual window limit.
config.max_prompt_tokens = 400_000
# truncate_len controls how many chars of REPL stdout the engine shows back to
# the model after each execution step. The default (2000) is too short for our
# skills (playbook.md is 5,353 chars). When truncated, the model compensates by
# manually printing the next slice (e.g. playbook[2000:4000]) in the next step —
# wasting a whole step + its growing-history overhead just to read content it
# already fetched. At 8000 chars, the longest skill fits in a single REPL output
# so the agent never needs to paginate, saving 3-4 steps and ~40-60k tokens per run.
config.truncate_len = 8000
# max_depth controls how many levels of llm_query() recursion are allowed.
# Tree: root planner (depth 0) → batch_llm_query lookup subagents (depth 1).
# Subagents call lookup_primitive() directly and emit FINAL immediately — they
# never need to go deeper. Setting 2 (not the default 3) makes that explicit
# and prevents accidental deeper recursion burning extra tokens.
config.max_depth = 2
# Flash calls complete in 2-8s. 30s is ample headroom; keep default.
# 3 retries kept in case of transient 429s at burst time.

print("✅ RLM Config created with Gemini adapter")