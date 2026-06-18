"""Smoke test: do the PULL tools work from INSIDE the Pyodide sandbox?

Host-Python proved the tool LOGIC. This proves the part that matters: a tool
running in the Deno/Pyodide REPL can (a) read DTCM_BACKEND_URL from os.environ
(injected via env_variables=), and (b) reach the host's uvicorn on
127.0.0.1:8001 through requests.

Prereqs:
  - backend up:  uv run uvicorn backend.server:app --port 8001
  - GEMINI_API_KEY set in .env  (rlm_config wires the rest)

Run:
  uv run python Task_test.py
"""

import fast_rlm
from pydantic import BaseModel

from rlm.rlm_config import config          # already Gemini-direct wired
from rlm.pull_tools import (
    list_primitives,
    lookup_primitive,
    list_skills,
    read_skill,
)


class PullProof(BaseModel):
    primitive_count: int        # len(list_primitives())
    box_param_names: list[str]  # keys of lookup_primitive("box")["parameters"]
    skill_names: list[str]      # list_skills()
    verification_planning_skill_content: str   # read_skill("verification_planning")


task = """
You are smoke-testing four HTTP tools pre-loaded in your REPL:
  - list_primitives()      -> list[str]
  - lookup_primitive(key)  -> dict
  - list_skills()          -> list[str]
  - read_skill(name)       -> str

Do EXACTLY this, then FINAL the result:
  1. list_primitives()             -> count them
  2. lookup_primitive("box")       -> take the keys of its "parameters"
  3. list_skills()
  4. read_skill("verification_planning")        -> get the returned text

FINAL a dict matching:
  {"primitive_count": int, "box_param_names": [str],
   "skill_names": [str], "verification_planning_skill_content": str}

If ANY tool raises, FINAL with primitive_count = -1 and put the exception
text into box_param_names so we can debug.
"""

# Flat run: 4 sequential calls need no subagent fan-out.
config.max_depth = 1
config.max_calls_per_subagent = 8

print("🚀 PULL smoke test (tools running INSIDE the sandbox)...\n")

try:
    result = fast_rlm.run(
        task,
        config=config,
        prefix="smoke_pull",
        tools=[list_primitives, lookup_primitive, list_skills, read_skill],
        env_variables={"DTCM_BACKEND_URL": "http://127.0.0.1:8001"},
        output_schema=PullProof,
    )
    r = result["results"]
    print("\n=== PULL SMOKE RESULT ===")
    print("primitive_count     :", r["primitive_count"])
    print("box_param_names     :", r["box_param_names"])
    print("skill_names         :", r["skill_names"])
    print("verification_planning_skill_content:\n", r["verification_planning_skill_content"])
    print("\nUsage:", result.get("usage"))
    print("Log  :", result.get("log_file"))

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()