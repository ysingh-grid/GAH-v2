"""
Load skills from SKILLS.md and inject into task context
"""

def load_skills_md() -> str:
    """Read SKILLS.md and return as string"""
    with open("skills/SKILLS.md", "r") as f:
        return f.read()


def inject_skills_into_task(task: str, skills_md: str) -> str:
    """
    Inject skills knowledge into the task prompt
    so the agent knows the strategies available
    """
    return f"""
{skills_md}

---

## YOUR TASK:

{task}

You have access to the above skills/strategies and the following tools.
Choose appropriate skills and tools to solve this task.
"""