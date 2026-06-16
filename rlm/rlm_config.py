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
config.primary_agent = "gemini-3.5-flash"
config.sub_agent = "gemini-3.5-flash"

print("✅ RLM Config created with Gemini adapter")