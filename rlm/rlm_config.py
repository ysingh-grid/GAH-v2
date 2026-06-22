"""
Fast-RLM configuration with Gemini adapter
"""

import os

from dotenv import load_dotenv
from pathlib import Path

from fast_rlm import RLMConfig


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file(Path(__file__).resolve().parents[1] / ".env")

# Set required environment variables for Gemini's OpenAI compatibility endpoint
os.environ["RLM_MODEL_BASE_URL"] = "https://generativelanguage.googleapis.com/v1beta/openai/"
os.environ["RLM_MODEL_API_KEY"] = os.environ.get("GEMINI_API_KEY", "")

config = RLMConfig.default()
# Tell fast-rlm to use Gemini models instead of the default z-ai/minimax models
config.primary_agent = "gemini-3.1-pro-preview"
config.sub_agent = "gemini-3.1-pro-preview"
config.max_depth = 2

print("✅ RLM Config created with Gemini adapter")
