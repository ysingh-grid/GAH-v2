import os
from dotenv import load_dotenv
import fast_rlm
from rlm.rlm_config import config
from tools.tools_registry import registry
from skills.skills_loader import load_skills_md, inject_skills_into_task

load_dotenv()

base_task = """
Generate 50 fruit names. Count how many contain the letter 'r'.

IMPORTANT INSTRUCTIONS FOR SUBAGENTS:
1. When you spawn a subagent, you MUST pass tools explicitly
2. Example: await llm_query("task here", tools=[count_letter, sum_numbers])
3. The subagent will NOT have tools unless you pass them
4. Subagents cannot access parent REPL variables - use explicit parameters

Strategy:
1. Generate 50 fruits (or use provided list)
2. Split into 2 groups (fruits 1-25, 26-50)
3. Call subagent 1: "Count r's in first 25 fruits" WITH tools=[count_letter]
4. Call subagent 2: "Count r's in second 25 fruits" WITH tools=[count_letter]
5. Combine counts using sum_numbers tool
6. Return FINAL(total)
"""

skills_md = load_skills_md()
full_task = inject_skills_into_task(base_task, skills_md)

print("🚀 Running task with Sub-Agents calling Tools...\n")

tools_list = registry.get_all()
print(f"[DEBUG] Main agent has {len(tools_list)} tools available\n")

try:
    result = fast_rlm.run(
        full_task,
        config=config,
        tools=tools_list  # ← Main agent gets tools
    )
    
    print(f"\n✅ Final Result: {result['results']}")
    print(f"Usage: {result['usage']}")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()