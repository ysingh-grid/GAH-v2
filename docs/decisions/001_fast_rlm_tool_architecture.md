# Architecture Decision Record: fast-rlm Tool Execution Constraints

## Context & Problem Statement

We observed that the agent using `fast-rlm` was unable to execute CAD tool logic (throwing `[Errno 138] emscripten does not support processes`) and crashed when trying to dynamically read skill files (`NameError: name '__file__' is not defined`).

This happens because `fast-rlm` enforces a secure architecture where **tools passed natively into the agent are injected into an isolated Pyodide (WebAssembly) sandbox.**

### The Constraints of Pyodide WebAssembly
Because Pyodide is an ephemeral, in-memory sandbox:
1. **No Host File System Access:** Functions cannot use `__file__`, `os.path.abspath`, or read from `/Users/...` to load dependencies like `library.json` or `SKILLS.md`.
2. **No Operating System Processes:** WebAssembly does not support spawning host processes, immediately failing any logic that relies on `subprocess.run()` (e.g., executing CadQuery and generating `.step` outputs).
3. **No File Persistence:** Any outputs written inside the sandbox are instantly deleted when the agent loop finishes; they never sync back to the host machine.

### Why the AI succeeded anyway (Prompt Injection vs. Dynamic Tools)
Despite the `read_skill` tool crashing, the agent successfully navigated the tasks because of **Prompt Injection**. The host orchestrator (`Task_test.py`) already loaded the contents of `SKILLS.md` using `skills_loader.py` and appended the text natively into the instruction prompt. 

However, `SKILLS.md` merely acted as an **index** (`Use read_skill(name) to load...`). The AI saw the index, tried to use the broken tool, failed, and simply hallucinated or guessed the basic code logic from its base training, meaning it **never actually read the deeper skill details** like `cadquery_cookbook`.

## Decision: Migrating to MCP (Model Context Protocol)

To grant the AI genuine access to the host's tools while honoring the fast-rlm sandbox model, we must shift the boundary of execution. 

Instead of executing tools *inside* the agent's WebAssembly loop, we will wrap the host tools inside a local **MCP Server**. 

### How it works
1. **Host Execution:** Tools like `execute_cadquery` and `read_skill` run natively on the host Mac, maintaining full access to the File System, `subprocess`, and persistent storage.
2. **MCP Bridge:** `fast-rlm` connects to the MCP Server as a client.
3. **Agent Invocation:** When the agent decides to invoke `read_skill("cadquery_cookbook")`, fast-rlm routes the request out of the sandbox to the MCP server. The server reads the file on the host and returns the string content back into the agent's context.

## Consequences

- **True Modularity:** We can add as many heavy host tools as needed without hitting WebAssembly memory limits.
- **Dependency Isolation:** C++ heavy dependencies like `MeshLib` or `CadQuery` do not need to be compatible with Pyodide.
- **Requirement:** We must implement the MCP server configuration before complex CadQuery verifications or dynamic skill-loading can function in the primary loop.
