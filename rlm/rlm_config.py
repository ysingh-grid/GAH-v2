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
# Tell fast-rlm to use Gemini models instead of the default z-ai/minimax models
config.primary_agent = "gemini-3.1-pro-preview"
config.sub_agent = "gemini-3.1-pro-preview"
# PRD gate: <5m per single-part workflow. Cap tool calls to force tight paths.
# Default is 20; 10 is enough for: playbook + list_primitives + 2× lookup +
# 1-2 ask_user turns + plan_ready. web_search counts against the same budget.
config.max_calls_per_subagent = 10

print("✅ RLM Config created with Gemini adapter")