# Geometry Agent Harness (GAH-v2) — Step 1: Planning & Clarification

This repository implements the first phase (Planning & Clarification MVP) of the **Geometry Agent Harness** (GAH), as described in the industrial specifications. 

It leverages [fast-rlm](https://github.com/google/fast-rlm) (Recursive Language Models) and the Model Context Protocol (MCP) to ingest engineering requirements, resolve design ambiguities interactively using GUI-based dialogs, and compile a structured, validated geometry plan.

---

## 🌟 Key Features

1. **Interactive Requirement Gathering**: Uses a host-level MCP server to spawn macOS AppleScript dialog boxes (`osascript`), prompting the user in real-time to resolve engineering ambiguities.
2. **Robust Schema Enforcement**: Validates all final plans against a Pydantic `GeometryPlan` model. A minimum length constraint on clarifications forces the LLM agent to interactively ask questions rather than bypassing user input.
3. **Hierarchical Sub-Agent Delegation**: Recursively delegates subtasks—such as hollowing case geometry or detailing mounting bracket hole coordinates—to parallel sub-agents to scale up planning complexity.
4. **Execution Tracing**: Features a trace visualizer to inspect the hierarchy of nested sub-agent calls, token budgets, and costs.

---

## 📂 Project Structure

*   [orchestrator.py](file:///Users/makumar/Documents/v3_capstone_ds/orchestrator.py) - The main entry point that configures model settings, runs the interactive CLI, registers host MCP tools, and invokes the RLM loop.
*   [run.yaml](file:///Users/makumar/Documents/v3_capstone_ds/run.yaml) - Execution and LLM generation configurations.
*   [trace_view.py](file:///Users/makumar/Documents/v3_capstone_ds/trace_view.py) - Renders the nested multi-agent execution hierarchy and usage metrics.
*   📂 [tools](file:///Users/makumar/Documents/v3_capstone_ds/tools/)
    *   [host_mcp.py](file:///Users/makumar/Documents/v3_capstone_ds/tools/host_mcp.py) - FastMCP host-level server containing:
        *   `ask_user`: Triggers the macOS GUI text input popup dialog box.
        *   `read_workspace_file`: Reads files from the workspace.
        *   `execute_python_package_check`: Performs a host package environment verification.
*   📂 [schemas](file:///Users/makumar/Documents/v3_capstone_ds/schemas/)
    *   [geometry_plan.py](file:///Users/makumar/Documents/v3_capstone_ds/schemas/geometry_plan.py) - The Pydantic model (`GeometryPlan`) defining overall bounding box dimensions, engineering requirements (functional, structural, thermal, cost), clarifications, assumptions, and the step-by-step CAD primitives build sequence.
*   📂 [skills](file:///Users/makumar/Documents/v3_capstone_ds/skills/)
    *   [core.md](file:///Users/makumar/Documents/v3_capstone_ds/skills/core.md) - System rules/planning guidelines injected into the agent's prompt context.

---

## 🛠️ Setup Instructions

### 1. Prerequisites
- macOS operating system (required for the AppleScript `osascript` GUI tool).
- Python 3.11+.

### 2. Create and Activate Virtual Environment
```bash
# Create a virtual env
python3 -m venv .venv

# Activate virtual env
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Create a `.env` file in the root directory and specify your key:
```env
RLM_MODEL_API_KEY="your-gemini-api-key"
```
*Note: If your key starts with `AIzaSy`, requests are automatically routed to the Google AI Studio endpoint.*

---

## 🚀 Running the Orchestrator

Execute the main orchestrator script:
```bash
python orchestrator.py
```
1. You will be prompted in the terminal for your CAD design request (e.g. *"Design an outdoor weather-resistant case for a Raspberry Pi 5 to be mounted on a metal pole"*).
2. The agent will run and trigger a GUI popup box on your macOS screen to clarify any critical ambiguities.
3. Once answered and validated, the final JSON plan is logged under the `logs/` directory.

---

## 📊 Viewing Execution Traces

To inspect the sub-agent hierarchy, call history, and token metrics:
```bash
python trace_view.py logs/<log_filename>.jsonl
```
Example output:
```text
● ROOT  depth=0  id=…eo6vr7
  · step 1: clarification_question_1 = "What is the diameter of the metal pole..."
  ✓ FINAL
  ● subagent  depth=1  id=…tf3mrh
    · step 1: cad_operations = []
    ✓ FINAL
    ● subagent  depth=2  id=…wsxnt4
      · step 1: # Extract information from the context
      ✓ FINAL
...
```
