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
# Hard safety-net cap on REPL steps per agent (the soft target lives in the prompt:
# root ~5-6 steps, leaf child ~3). Too low STARVES the root orchestrator — it needs
# probe + read-task + list_primitives + decompose + batch-fork + process + assemble
# + FINAL (~7-8 steps); hitting the cap before FINAL throws "Did not finish the
# function stack before subagent died". 8 was too tight. 12 gives the root margin.
# NOTE: this is NOT the token-balloon guard — max_depth=1 is (it stops the recursive
# grandchild fan-out). With depth capped, only ~6 agents exist, so a higher step cap
# does not re-balloon the cumulative token budget.
config.max_calls_per_subagent = 12
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
# max_depth caps llm_query() recursion. The engine makes an agent at depth ==
# max_depth a LEAF: its llm_query is removed and any fork attempt throws. So
# max_depth=1 means root planner (depth 0) forks ONE level of sub-part agents
# (depth 1), and those children are LEAVES — they cannot fork grandchildren.
# This is the hard, engine-level enforcement of strict 1-to-1 fork-and-return;
# without it (default 3, or even 2) children recursively fork and the cumulative
# prompt-token budget explodes (observed 459k tokens from a depth-2 fan-out).
config.max_depth = 1
# Flash calls complete in 2-8s. 30s is ample headroom; keep default.
# 3 retries kept in case of transient 429s at burst time.

print("✅ RLM Config created with Gemini adapter")