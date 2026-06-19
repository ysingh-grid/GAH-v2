# fast-rlm ForgeCAD Natural-Language-to-CAD Compiler

This repository implements a fully automated, compile-ready **Natural-Language-to-CAD Compiler** using the [fast-rlm](https://github.com/google/fast-rlm) (Recursive Language Model) framework and the **Model Context Protocol (MCP)**.

It coordinates recursive, self-correcting agents to plan, write, and compile 3D parametric CAD models directly from custom, natural-language prompts.

---

## 📂 Project Structure

*   `orchestrator_cad.py` - The main entry point to configure runs, load schemas, spin up the local MCP server, and launch the RLM runner with custom prompts from command-line arguments.
*   `run_cad.yaml` - Execution configurations (model overrides, depth limits, token thresholds, parameters).
*   `todos.txt` - The target list of completed milestones, rules, and guidelines.
*   `trace_view.py` - Visualizes the hierarchical agent execution tree, token expenditures, and cost details.
*   📂 `tools/`
    *   `write_workspace_file.py` - Modular tool that writes generated code to the local file system.
    *   `export_forgecad_to_stl.py` - Modular tool that compiles .forge.js code to binary STL mesh files using host-level command-line processes.
    *   `check_environment.py` - Harmless, local python tool that ensures sandbox environment readiness.
    *   `host_mcp.py` - FastMCP server providing safe system-level and OS capabilities to sandboxed agents.
*   📂 `schemas/`
    *   `cad_generation.py` - Strictly enforces file layout and compile-time success using native JSON Schema patterns and `"const"` true constraints.
*   📂 `skills/`
    *   `forgecad_designer.md` - Streamlined core compiler skills, primitives reference, and Pyodide REPL-safety guidelines.
    *   `forgecad-*.md` - Official expert ForgeCAD companion skills dynamically loaded by the router based on your prompt's keywords.

---

## 🛠️ Setup Instructions

### 1. Prerequisites
Ensure you have Python 3.11+ and Node.js/npm installed on your machine.

### 2. Create and Activate Virtual Environment
```bash
# Create a virtual environment
python3 -m venv venv

# Activate on macOS/Linux
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Create and Configure Environment Credentials
Create a `.env` file in the root directory:
```bash
RLM_MODEL_API_KEY=your_api_key_here
FORGECAD_TOKEN=your_forgecad_token_here
```

---

## 🚀 Running the Compiler

To compile any custom natural-language CAD design request into a fully parametric `.forge.js` script and a binary `.stl` mesh model, execute the orchestrator with your design request inside quotes:

```bash
python orchestrator_cad.py "Design a hollow box of size 40x40x40 with a wall thickness of 2"
```

The system will automatically:
1.  Spin up the Host MCP tools server.
2.  Dynamically load the core designer skills and keyword-matched companion skills (e.g. assemblies).
3.  Recursively think, plan, write, and compile your CAD script.
4.  **Save both the script and the STL mesh inside a dedicated folder** under `outputs/<design_name>/`.
5.  Render a beautiful execution trace log on your terminal!
