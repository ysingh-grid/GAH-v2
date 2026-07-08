# GAH-v2 — Geometry Agent Harness Codebase Guide

Welcome to the comprehensive technical guide for **GAH-v2 (Geometry Agent Harness)**. This document serves as a detailed deep-dive into the system's architecture, core data flows, file structures, RLM (Re-Plan Loop Mechanism) configuration, and runtime components.

---

## 1. System Architecture & Components

The system is split into multiple distinct layers that work together to translate a natural language prompt into a physical, watertight, and visually verified 3D CAD model.

```
                  ┌──────────────────────────────────────────────┐
                  │              Frontend UI (/ui)               │
                  │  Static HTML/JS chat box with WebSocket connection
                  └──────────────────────┬───────────────────────┘
                                         │
                                         ▼ (WebSocket /designs/{id}/chat)
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                FastAPI Server (backend/)                                │
│                                                                                         │
│  - app.py & server.py: App wireup and ASGI entrypoints                                  │
│  - intake.py: Multi-turn conversational clarification chatbot                           │
│  - runner.py: Orchestrates session status, calls RLM, and starts the Geometry Loop       │
└────────────────────────────────────────┬────────────────────────────────────────────────┘
                                         │
                                         ├──────────────────────────┐
                                         ▼ (In-Process)             ▼ (Distributed)
┌────────────────────────────────────────────────────────────────┐  ┌─────────────────────┐
│                       Geometry Pipeline                        │  │  Temporal Cluster  │
│                                                                │  │                     │
│  1. compile_cadquery.py: Translates PrimitivePlan -> Python   │  │  activities.py:     │
│  2. execute_cadquery.py: Spawns sub-process executing CQ script│  │  Durable wrappers   │
│  3. inspect_mesh.py & repair_mesh.py: Watertight check & patch │  │  around geometry    │
│  4. render_views.py: Renders multi-angle 2D PNG views of STL   │  │  loop stages.       │
│  5. vlm_judge.py: Multi-modal Gemini judge verifies output     │  │                     │
│  6. replan.py: Executes replanner on fail (up to cap limit)     │  │  workflow.py:       │
└────────────────────────────────────────────────────────────────┘  │  Durable state logic│
                                                                    └─────────────────────┘
```

---

## 2. Core Pipelines & Step-by-Step Data Flow

When a user types a prompt (e.g., *"An aerodynamic turbine blade"*), the system progresses through the following precise pipeline:

### Step 1: Pre-Planner Clarification Intake
* **Class:** `backend/designs/intake.py` and `tools/vlm_intake.py`.
* **Flow:** 
  1. The user's input text (and optional images) are captured.
  2. The intake chatbot uses a direct Gemini call (`gemini-3.5-flash` for low-latency) with `ThinkingLevel.LOW` to assess the input.
  3. Rather than asking a blind list of static questions, it evaluates the conversation transcript turn-by-turn. It decides whether to ask **exactly one more clarifying question** about size, feature counts, or critical placement, or declare itself **satisfied**.
  4. Once satisfied (or after a hard ceiling of `MAX_INTAKE_QUESTIONS = 5`), it formats a markdown list of `established facts` and hands them to the planner. This prevents the downstream planner from generating geometry based on blind assumptions.

### Step 2: RLM Planning
* **Class:** `runtime/planner.py`.
* **Flow:** 
  1. The primary planner agent, powered by the robust `gemini-3.1-pro-preview` model via `fast-rlm`, takes the original prompt and the gathered intake context.
  2. Operating within a single-block REPL execution, it invokes tools like `list_primitives` and `lookup_primitive` to query the CAD primitive catalog (`primitives/library.json`).
  3. It generates a **`PrimitivePlan` JSON object**, matching the Pydantic schemas defined in `runtime/schema.py`. This plan contains an ordered tree of physical steps (CSG operations: `base`, `union`, `cut`, `intersect`) with exact coordinates, dimensions, orientations, and post-body modifiers (fillet, chamfer, shell).

### Step 3: Geometry Compilation & Execution
* **Class:** `runtime/compile_cadquery.py` and `tools/execute_cadquery.py`.
* **Flow:**
  1. The `PrimitivePlan` JSON is compiled deterministically into an executable **CadQuery Python script**.
  2. This script is spawned as an isolated process on the host (or inside the container).
  3. CadQuery executes the script and writes the resulting 3D geometry as an **STL mesh** to disk.

### Step 4: Mesh Inspection & Repair
* **Class:** `tools/inspect_mesh.py` and `tools/repair_mesh.py`.
* **Flow:**
  1. The STL mesh is verified by MeshLib to check if it is **watertight** and physically valid.
  2. If the parts touch but do not overlap, creating separate shells (a standard CSG failure), the mesh fails.
  3. `repair_mesh` uses MeshLib to attempt to fix watertight issues, fuse components, or patch holes. If repair fails, the loop routes a detailed error back to the replanner.

### Step 5: Rendering & VLM Verification
* **Class:** `tools/render_views.py` and `tools/vlm_judge.py`.
* **Flow:**
  1. If the mesh is valid, VTK/Trame renders multi-angle snapshots of the 3D model into a combined **PNG image**.
  2. The VLM Judge (`gemini-3.1-pro-preview` with `ThinkingLevel.LOW` and a large token budget) receives the original prompt, the render PNG, and the previous replan feedback.
  3. The judge outputs a JSON verdict. If it detects anomalies (e.g., a flat blade instead of curved), it fails the run and generates detailed constructive feedback.

### Step 6: Stateful Replanning Loop
* **Class:** `runtime/replan.py`.
* **Flow:**
  1. If any stage fails (compile error, mesh watertightness failure, or visual mismatch), the loop calls the replanner.
  2. The replanner receives a comprehensive, stateful history containing previous failed plans, their failure logs, and constructive feedback from the judge.
  3. The replanner analyzes the feedback against its skills (`skills/repair_guidance.md` or `skills/refinement_guidance.md`) and emits a corrected `PrimitivePlan`.
  4. To optimize performance, if the replanned plan is unchanged after a verifier error (meaning a temporary transport issue occurred, not a code flaw), it short-circuits directly to re-verify, skipping compiling/rendering.

---

## 3. Directory & File Breakdown

### Root Directory
* **`restart.sh`**: The master orchestration script that stops active Docker containers, builds fresh layers, and spins up the full durable stack with profiling.
* **`Makefile`**: Standard targets for local dev live-reload (`make dev`, `make dev-temporal`), prod builds (`make up`), and container status checking (`make ps`).
* **`pyproject.toml` & `uv.lock`**: Managed dependencies including FastAPI, Google GenAI SDK, fast-rlm, CadQuery, and MeshLib.

### `backend/` — API & Core Orchestration
* **`server.py`**: ASGI entrypoint launching Uvicorn on port `8001`.
* **`app.py`**: Builds the FastAPI app, configures CORS, serves static frontend UI files under `/ui`, and wires up routers.
* **`designs/`**:
  * `routes.py`: Websocket handler (`/chat`) and HTTP routes for session management.
  * `intake.py`: Turn-by-turn conversational intake chatbot.
  * `runner.py`: Orchestrates the chat-turn. Determines if a message is a fresh query, clarification, question, or an edit, and routes to in-process or Temporal pipelines.

### `runtime/` — Pure Core Logic (No Web/Temporal dependencies)
* **`planner.py`**: Interacts with `fast_rlm` to produce a primitive plan. Exposes the RLM tools.
* **`loop.py`**: The main geometry pipeline orchestrator. Contains the loop boundaries and passes data through compile, execution, inspection, and verification.
* **`replan.py`**: Generates failure logs and builds feedback prompts for the replanner.
* **`compile_cadquery.py`**: Transpiles the primitive JSON plan into CadQuery Python code.
* **`schema.py`**: Core Pydantic schemas validating the PrimitivePlan.

### `temporal/` — Durable Pipeline (Fault-Tolerant Scheduling)
* **`shared.py`**: Connects clients and worker pools to Temporal namespace.
* **`activities.py`**: Wraps the steps of the geometry loop into distinct activities with background thread heartbeating (every 10s) to prevent workers from hanging.
* **`workflow.py`**: Orchestrates the durable, persistent state machine of the design run.
* **`worker.py`**: Executable that registers and runs activities and workflows under the `gah-design` task queue.

### `tools/` — CAD, Rendering, and AI Helpers
* **`execute_cadquery.py`**: Executes compiled Python scripts in an isolated process to output STL.
* **`inspect_mesh.py` & `repair_mesh.py`**: Checks mesh watertightness and runs automated MeshLib repairs.
* **`render_views.py`**: Generates high-fidelity visual representations of the 3D model.
* **`vlm_judge.py`**: Prompts the Gemini-Pro model to visually audit the renders.
* **`vlm_intake.py`**: Contains system prompts and schemas for both VLM summarization and conversational intake turns.

### `skills/` — AI Persona & System Playbooks
* **`playbook.md`**: Foundational rules guiding the RLM Planner to output valid schemas on the first turn.
* **`repair_guidance.md`**: Teaches the agent how to fix compilation, execution, and watertightness errors.
* **`refinement_guidance.md`**: Guide for interpreting and fixing visual mismatch reports from the VLM judge.
* **`dimension_reasoning.md`**: Strict offset calculations and dimension stacking rules.

---

## 4. RLM Configuration & Optimization Details

The file **`rlm/rlm_config.py`** is the brain of the agent's execution parameters. It has been meticulously configured to maximize reasoning ability while strictly bounding token bloat and latency:

```python
config.primary_agent = "gemini-3.1-pro-preview"
config.sub_agent = "gemini-3.5-flash"
```
* **Pro Root Agent:** Using a powerful reasoning model like Pro-3.1 for the root driver ensures that the agent successfully decomposes complex structures and reasons in fewer REPL turns. This prevents the quadratic cost growth of re-submitting history over dozens of low-quality turns.
* **Flash Sub-Agent:** Flash-3.5 is used for lightweight leaf-node execution (e.g., delegate_features sub-parts) to keep token costs minimal.

```python
config.max_depth = 1
```
* **Recursion Guard:** Restricts sub-agent delegation to exactly 1 level. This hard-bounds recursive grandchild fan-out (which previously caused prompts to inflate up to 500k+ tokens).

```python
config.max_calls_per_subagent = 20
config.truncate_len = 12000
```
* **Execution Margins:** Sets a limit of 20 REPL steps to prevent infinite loops, combined with an elevated truncation limit of 12,000 characters. Sizing `truncate_len` generously ensures that skills (like the 8KB `playbook.md`) are returned in a single step without forcing the agent to manually slice and request the file over multiple expensive turns.

---

## 5. Visual Feedback Loop & Mesh Taxonomy

When failures occur, they are strictly categorized into a **6-category taxonomy** (defined in `runtime/trace.py`) which is persisted inside `trace.json` to monitor system performance:

| Category | Trigger Stage | Description | Common Resolution |
| :--- | :--- | :--- | :--- |
| **`primitive_gap`** | Compile | Requested shape cannot be expressed with the catalog. | Replanner falls back to CSG approximation. |
| **`cadquery_compile`** | Compile | Syntactical transpiler failures. | Replanner corrects parameter types/keys. |
| **`cadquery_execute`** | Execution | Runtime exception (e.g. invalid face selector). | Replanner corrects the CadQuery selector string. |
| **`mesh_repair`** | Inspection | Non-watertight mesh or disconnected components. | Replanner sinks union features 0.5-1mm deeper. |
| **`visual_mismatch`** | Verification | VLM Judge rejects the shape (e.g., wrong proportions). | Replanner shifts scales, angles, or adds features. |
| **`unclear`** | Exception | Unexpected system transport exceptions. | System triggers an automatic retry. |

---

## 6. Testing Harness

The test suite is highly thorough, testing all aspects of both local, in-process, and containerized durable flows:

* **Unit Tests (`tests/test_schema.py`, `tests/test_compile_cadquery.py`)**: Validates the Pydantic plan parsing and the transpilation process.
* **Durable Tests (`tests/test_temporal.py`, `tests/test_docker.py`)**: Audits workflow persistence, worker heartbeats, and correct container setups.
* **End-to-End Tests (`tests/test_loop.py`, `tests/test_vlm_judge.py`)**: Executes actual geometry pipeline runs, mesh evaluations, rendering, and visual judging.

To execute the suite locally, run:
```bash
uv run pytest
```

---

*This guide was generated automatically to assist in rapid codebase understanding. Use it as a structural map when adding new primitives, refactoring routes, or extending workflow activities.*
