# ForgeCAD Agent Skill: Sub-Agent Delegation Protocol

You are operating inside the multi-agent `fast-rlm` framework. When designing complex models or large assemblies, you can act as a **Chief Architect** and spawn specialized sub-agents to construct individual parts, bypassing context and step budget limitations.

---

## 📋 The Delegation Protocol

To prevent **Context Amnesia** (where a spawned child agent forgets the core ForgeCAD rules and starts hallucinating non-ForgeCAD or OpenSCAD syntax), you MUST follow these non-negotiable guidelines:

### 1. Read Core Skills First
Before calling `llm_query`, you must read the core compiler rules from the filesystem. This guarantees you have the exact system prompts to pass down:
```python
core_rules = await mcp_call('host_tools', 'read_workspace_file', filename='skills/forgecad_designer.md')
```

### 2. Explicit Context Injection
When calling `llm_query()`, you MUST explicitly inject these core rules into the `context={"role_instructions": ...}` parameter of the payload. Child agents do NOT inherit your parent skills by default:
```python
# Create a specialized Coder subagent with correct instructions
sub_context = {"role_instructions": core_rules}
subagent_prompt = (
    "You are a specialized ForgeCAD Coder. "
    "Write a parametric chair seat-pan with rounded front corners. "
    "Use only the global APIs defined in your role_instructions. "
    "Return ONLY the clean JavaScript code string, ending with 'return seat;'."
)

seat_code = await llm_query(subagent_prompt, context=sub_context)
```

### 3. Clear Task Separation
*   **Parent Agent (Architect)**: Decomposes the prompt, coordinates child queries, and assembles the parts using the Component Model (`group(...)`).
*   **Child Agent (Coder)**: Writes the Javascript code for a single, isolated part. It must focus entirely on geometry and parameter definitions.

### 4. Code Assembly
After receiving the code strings from your sub-agents, combine them logically into one cohesive `.forge.js` script.
- Ensure parameters are defined at the very top of the script.
- Ensure the individual parts are written sequentially.
- Combine and return them using `group()`:
```javascript
const finalAssembly = group(
  { name: "Base", shape: baseShape },
  { name: "Seat", shape: seatShape },
  { name: "Back", shape: backShape }
);
return finalAssembly;
```
