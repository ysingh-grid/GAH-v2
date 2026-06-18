# Recursive Language Model (fast-rlm) Capstone Project

This project implements a multi-agent orchestration framework leveraging [fast-rlm](https://github.com/google/fast-rlm) (Recursive Language Models) and the Model Context Protocol (MCP) to perform automated analysis, multi-agent reasoning, and workspace file tool usage.

---

## 🌟 Key Features

1. **Recursive Agent Loop**: Automatically spawns nested sub-agents using [fast_rlm](file:///Users/makumar/Documents/v3_capstone_ds/orchestrator.py#L18) for multi-layered reasoning.
2. **Local MCP Server**: Leverages a custom [FastMCP](file:///Users/makumar/Documents/v3_capstone_ds/tools/host_mcp.py#L7) server (`HostTools`) to safely query and interact with workspace documents.
3. **Structured Validation**: Uses Pydantic to ensure all final results conform strictly to a predefined schema.
4. **Execution Tracing**: Renders full tree visualizations of agent calls, token budgets, and costs.

---

## 📂 Project Structure

*   [orchestrator.py](file:///Users/makumar/Documents/v3_capstone_ds/orchestrator.py) - The main entry point to configure runs, load schemas, spin up the local MCP server, and launch the RLM runner.
*   [run.yaml](file:///Users/makumar/Documents/v3_capstone_ds/run.yaml) - Execution configurations (model overrides, depth limits, token thresholds, parameters).
*   [todos.txt](file:///Users/makumar/Documents/v3_capstone_ds/todos.txt) - The target list of rules, guidelines, and objectives.
*   [trace_view.py](file:///Users/makumar/Documents/v3_capstone_ds/trace_view.py) - Visualizes execution hierarchy, token consumption, and dollar costs.
*   📂 [tools](file:///Users/makumar/Documents/v3_capstone_ds/tools/)
    *   [calculate_string_length.py](file:///Users/makumar/Documents/v3_capstone_ds/tools/calculate_string_length.py) - Calculates length of fruit names.
    *   [count_vowels.py](file:///Users/makumar/Documents/v3_capstone_ds/tools/count_vowels.py) - Counts vowels for long words.
    *   [host_mcp.py](file:///Users/makumar/Documents/v3_capstone_ds/tools/host_mcp.py) - FastMCP server providing local workspace tools like [read_workspace_file](file:///Users/makumar/Documents/v3_capstone_ds/tools/host_mcp.py#L10) and [execute_python_package_check](file:///Users/makumar/Documents/v3_capstone_ds/tools/host_mcp.py#L29).
*   📂 [schemas](file:///Users/makumar/Documents/v3_capstone_ds/schemas/)
    *   [fruit_analysis.py](file:///Users/makumar/Documents/v3_capstone_ds/schemas/fruit_analysis.py) - Holds the Pydantic verification schema [FruitAnalysisItem](file:///Users/makumar/Documents/v3_capstone_ds/schemas/fruit_analysis.py#L4).
*   📂 [skills](file:///Users/makumar/Documents/v3_capstone_ds/skills/)
    *   [core.md](file:///Users/makumar/Documents/v3_capstone_ds/skills/core.md) - System rules/instructions injected into the agent's prompts.

---

## 🛠️ Setup Instructions

### 1. Prerequisites
Ensure you have Python 3.11+ installed.

### 2. Create and Activate Virtual Environment
```bash
# Create a virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy the template file to `.env`:
```bash
cp .env.template .env
```
Open `.env` and specify your credentials:
```env
RLM_MODEL_API_KEY="your-api-key"
```
> [!NOTE]
> If your API key begins with `AIzaSy`, `orchestrator.py` automatically routes requests to the Google AI Studio endpoint via the OpenAI compatibility layer.

---

## 🚀 Running the Orchestrator

Execute the main orchestrator script:
```bash
python orchestrator.py
```

Upon run completion, execution logs will be written to the `logs/` directory as JSONL files.

---

## 📊 Viewing execution traces

To inspect sub-agent hierarchy, call history, and token usages:
```bash
python trace_view.py logs/<log_filename>.jsonl
```

Or view it using the built-in TUI:
```bash
fast-rlm-log logs/<log_filename>.jsonl --tui
```
