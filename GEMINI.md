# GEMINI.md

Welcome to the `v3_capstone` project! This document serves as the foundational instructional context and reference guide for AI assistants (like Gemini CLI) interacting with this workspace.

---

## 1. Project Overview

The `v3_capstone` project is a fully automated, compile-ready **Natural-Language-to-CAD Compiler** powered by the **`fast-rlm`** (Recursive Language Model) framework. 

It executes recursive, self-correcting LLM agents that coordinate to plan, write, and compile 3D parametric CAD models based on arbitrary, natural language user prompts (e.g. *"Design a hollow box of size 40x40x40 with a wall thickness of 2"*).

### Core Technologies
- **Python 3**: The main programming language.
- **fast-rlm**: The core library facilitating recursive agent execution and planning.
- **Pydantic**: Used for strict, JSON-schema-enforced output validation.
- **Model Context Protocol (MCP)**: Used via `mcp` (FastMCP) to run host-level tool servers that bypass WebAssembly sandbox process limits.
- **ForgeCAD**: The code-first parametric 3D CAD library (via Node.js/CLI) used to compile Javascript models into STL meshes.

### Directory Structure & Architectural Flow
```text
v3_capstone/
├── .env                       # Environment credentials (API keys)
├── run_cad.yaml               # Configuration file (agents, limits, tools, paths)
├── orchestrator_cad.py        # Main natural language compiler entrypoint
├── trace_view.py              # Visualizes agent execution logs
├── todos.txt                  # Roadmap, requirements, and target exercises
├── schemas/
│   └── cad_generation.py      # Pydantic/JSON-Schema model for compile-time correctness
├── skills/
│   ├── forgecad_designer.md   # Dynamic, consolidated core compiler skills
│   └── forgecad-*.md          # Expert ForgeCAD companion skills
└── tools/
    ├── __init__.py            # Tool Registry and retrieval logic
    ├── write_workspace_file.py # Modular tool for saving script code
    ├── export_forgecad_to_stl.py # Modular tool for compiling JS to STL (with auto-shims)
    ├── check_environment.py   # Modular tool for sandboxed health verification
    └── host_mcp.py            # FastMCP Server exposing system-level tools to sandbox
```

1. **Orchestrator (`orchestrator_cad.py`)**:
   - Accepts any custom design prompt in natural language via command-line arguments:
     ```bash
     python orchestrator_cad.py "Design a solid cylinder of height 50 and radius 15"
     ```
   - Automatically loads Pydantic verification schemas and prepends dynamic, keyword-based expert skill modules (like `forgecad-component-model.md` for assemblies) to preserve a lean context.
   - Spins up a local `FastMCP` background host server (`tools/host_mcp.py`) and passes it alongside local functions as tool definitions to `fast_rlm.run`.
   - Captures telemetry logs and triggers `trace_view.py` on completion to render an execution tree.

2. **Airtight Verification Schema (`schemas/cad_generation.py`)**:
   - Uses strict `"pattern"` regex constraints to enforce output file placement under `outputs/<design_name>/`.
   - Enforces compile-time success using `Literal[True]` and a custom `compilation_logs` validator that rejects any submissions containing error logs, strictly forcing the agent to retry and self-correct syntax until successful compilation is achieved.

3. **General-Purpose Skills (`skills/forgecad_designer.md`)**:
   - Defines critical compiler rules, global positional primitives (box, cylinder, ngon, extrude), and a python line-by-line list-of-strings writing pattern that completely prevents Python triple-quote parsing syntax errors inside Pyodide.

4. **Host-Level MCP Tools (`tools/`)**:
   - Exclusively exposes `write_workspace_file` and `export_forgecad_to_stl` via the HostMCP server (`host_mcp.py`), resolving paths relative to the project root. This allows the sandboxed WebAssembly engine (which cannot spawn OS commands) to safely write and compile STL models on the host operating system.

---

## 2. Advanced Compiler Features

To guarantee 100% successful compile-to-STL runs under any natural language prompt, the compiler incorporates several high-level, robust engineering architectures:

### ⚙️ Airtight JSON Schema Constraints (`schemas/cad_generation.py`)
To prevent the agent from "lying" about compile success to bypass validation checks, constraints are bound directly into the **raw JSON Schema** at the Gemini API level:
*   **Compile-Time Success Constraint (`success: Literal[True]`)**: Compiles to `"const": true` in JSON Schema. This strictly forbids the LLM from returning `success: false`, forcing it to achieve successful compilation.
*   **Error-Free Log Constraint (`compilation_logs` field validator)**: If the compiler returns error messages (like `ERROR: CSG is not defined`), our Python-level validator raises a Pydantic `ValidationError`. This rejects the result and forces the agent's internal loop to self-correct.
*   **Directory Pattern Constraint (`Field(pattern=...)`)**: Uses standard regular expressions to compile directly into JSON Schema `"pattern"` properties, forcing the agent to write and compile files exclusively within `outputs/<design_name>/model.forge.js` and `outputs/<design_name>/model.stl`.

### 🔄 Robust Compile-Time Auto-Shims (`tools/export_forgecad_to_stl.py`)
To prevent transient compilation crashes due to standard JSCAD/OpenSCAD priors, our compiler automatically scans and shims generated JS scripts on the fly before passing them to ForgeCAD:
*   **Uncalled Handoffs (`function main()`)**: If the agent wraps its code in a `function main() { ... }` block but forgets to call or export it, our compiler automatically appends:
    `if (typeof main === 'function') { return main({}); }`
*   **Loose Expressions (`ngon(...)`)**: If the agent writes a sequential 2D/3D primitive statement but forgets to prepend the global `return` keyword, our compiler automatically prepends `return ` to the expression line.
*   **Missing Variable Returns (`const triangle = ...`)**: Automatically appends `return triangle;` or `return bracket;` if the variable is defined but not returned in the global scope.

### 🔀 Dynamic Skill Router Architecture (`orchestrator_cad.py`)
To keep the prompt context lean and fast while ensuring deep domain-level expertise, we implemented an **Intelligent Dynamic Skill Router**. It scans your natural language prompt and selectively loads companion skills as "plugins" on demand:
*   *Default*: Loads core compiler syntax rules from `skills/forgecad_designer.md`.
*   *Assembly / Joint / Mate*: Loads `skills/forgecad-component-model.md` for multi-part positioning and connectors.
*   *Image / Photo / Replicate*: Loads `skills/forgecad-image-replicator.md` for 3D reconstruction from reference images.
*   *Blockout / Concept / Rough*: Loads `skills/forgecad-blockout-model.md` for conceptual prototyping.

### 🛡️ Complete Sandbox/Host Segregation (`tools/__init__.py`)
To prevent process execution or file-system exceptions within Pyodide's virtual WebAssembly sandbox:
*   All file-writing and compiling capabilities are completely removed from Pyodide local python tools.
*   The Pyodide sandbox is registered with a harmless, dependency-free local tool `check_environment` to satisfy empty-tools-list parameters and prevent HTTP 400 Bad Request errors.
*   All real CAD capabilities run exclusively on the host operating system via the `HostTools` MCP server, where the workspace root is resolved securely using `Path(os.getcwd())`.

---

## 3. Running & Verification

### Environment Setup
Create a `.env` file in the root directory:
```bash
RLM_MODEL_API_KEY=your_gemini_api_key_here
FORGECAD_TOKEN=your_forgecad_token_here
```

### Dependencies
Install the required dependencies manually:
```bash
pip install pyyaml pydantic python-dotenv mcp
```

### Key Commands

- **Compile Natural Language to CAD**:
  ```bash
  python orchestrator_cad.py "Design a hollow box of size 40x40x40 with a wall thickness of 2"
  ```
  *(This compiles the hollow box, or any other geometry into a dedicated Outputs folder).*

- **Visualize Execution Trace Log**:
  ```bash
  python trace_view.py logs/<log_filename>.jsonl
  ```
  *(Renders the hierarchical agent tree, token expenditures, and cost details).*

---

## 4. Development Conventions

1. **Host-Powered MCP Tooling**:
   - Because `fast-rlm` sub-agents run in a sandboxed WebAssembly (Pyodide) environment that does not support process spawning, **all tools that write files or execute CLI processes must run exclusively via Host MCP (`tools/host_mcp.py`)** so they execute on the real host machine.

2. **Line-by-Line List Writing**:
   - When generating code, always construct scripts as lists of single-quoted string lines joined with newlines rather than using multi-line triple-quoted string blocks to avoid Python string parsing clashes inside the REPL.

3. **Closed-Loop Verification**:
   - Always verify that the Pydantic schema pattern, Literal constraints, and error-free validators remain active, as they are the primary force driving the agent's self-correcting code generation loop.

4. **Preventing Sub-Agent Context Amnesia**:
   - When using `llm_query` inside python REPL steps to delegate tasks to child sub-agents, always explicitly pass your `role_instructions` down inside the `context` parameter of your `llm_query` call. By default, `fast-rlm` child sub-agents do not inherit parent system prompts.
