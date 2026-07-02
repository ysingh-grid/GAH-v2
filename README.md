# GAH-v2 — Local AI Geometry Agent Harness (Native Full-Stack)

GAH-v2 is an advanced, AI-powered CAD design system. It takes natural language design requests, clarifies parameters interactively, generates plan structures, and compiles them into verified 3D geometry via durable local Temporal workflows.

---

## Native Architecture

```text
┌─────────────────────────────────────────────┐
│  Frontend UI: /ui/ (Port 8001)              │
│  - Elegant Form-based Light Theme           │
│  - Run History Table + Analytics Dashboard  │
│  - Real-Time Live Trace "Brain" Console     │
└──────────────┬──────────────────────────────┘
               │ (WebSocket: /designs/{id}/chat)
        ┌──────▼──────┐
        │ FastAPI App │ (Port 8001)
        └──────┬──────┘
               │ (Distributed Task Queue)
        ┌──────▼──────────────────────────────┐
        │ Native Temporal Server (Port 8233)  │
        │ - Handles background task execution │
        │ - Keeps loops alive across timeouts  │
        └─────────────────────────────────────┘
```

The system is designed to run completely natively on your machine, eliminating the need for Docker containerization. It uses standard FastAPI WebSocket handlers and local Temporal workflows to handle high-compute CAD compiles in the background.

---

## Quick Start (Native Execution)

### 1. Configure Credentials
Create a `.env` file in the root of your project directory:
```env
# Required for RLM planning and VLM/intake analysis
GEMINI_API_KEY=your_actual_gemini_api_key_here
# Tell the backend to use the local native Temporal server
TEMPORAL_HOST=localhost:7233
```

### 2. Start the Temporal Server (Native CLI)
Install the [Temporal CLI](https://learn.temporal.io/getting_started/python/dev_environment/) and run the development server natively:
```bash
temporal server start-dev
```
*(This starts the Temporal Engine on port `7233` and its Web Dashboard on port `8233`).*

### 3. Start the Python Backend & Worker
In a new terminal, synchronize your dependencies and boot the FastAPI development server:
```bash
# Sync local environment packages (installs temporalio, fast-RLM, CadQuery, etc.)
uv sync

# Start the server natively with hot-reload enabled
make dev
```
*(Alternatively, run: `uv run uvicorn backend.server:app --host 0.0.0.0 --port 8001 --reload`)*

### 4. Visit the Control UI
Open your browser and navigate to:
**`http://localhost:8001/ui/`**

From this single, beautiful web dashboard, you can control and view the entire system:
- **Design & Generate:** Submit design prompts and view real-time AI thoughts and pretty-printed plans in the console.
- **Run History:** Table showing past runs, allowing you to instantly **"Resume"** past chat sessions.
- **Temporal Dashboard:** Click the sidebar link to monitor workflows directly in the native Temporal UI (`http://localhost:8233`).

---

## Running Local Unit Tests
You can run the full, comprehensive unit test suite locally to verify that all endpoints, compilers, and Temporal integrations are completely green:
```bash
# Run the 160+ test cases
make test
```

## RLM Backend Bridge

The project also includes a FastAPI bridge for sandboxed RLM tool access. Start it from the project root:

```bash
bash scripts/start_backend.sh
```

Then run the smoke test or full backend demo:

```bash
python scripts/rlm_backend_smoke.py
python scripts/run_full_rlm_backend_demo.py
```

The bridge exposes skills, safe repo/file access, allowlisted project tools, pipelines, output inspection, and traces through `/internal/*` JSON endpoints.
