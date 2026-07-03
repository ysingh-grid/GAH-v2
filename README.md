# GAH-v2 — Local AI Geometry Agent Harness

GAH-v2 is an advanced, AI-powered CAD design system. It takes natural language design requests, clarifies parameters interactively, generates plan structures, and compiles them into verified 3D geometry via durable local Temporal workflows.

---

## The "One-Click" Native Architecture

```text
┌─────────────────────────────────────────────┐
│  Frontend UI: /ui/ (Port 8001)              │
│  - Elegant Form-based Light Theme           │
│  - Run History Table + Analytics Dashboard  │
│  - Real-Time Live Trace "Brain" Console     │
│  - One-Click Temporal Engine Control        │
└──────────────┬──────────────────────────────┘
               │ (WebSocket: /designs/{id}/chat)
        ┌──────▼──────┐
        │ FastAPI App │ (Port 8001)
        └──────┬──────┘
               │ (Managed Subprocess)
        ┌──────▼──────────────────────────────┐
        │ Native Temporal Server (Port 8233)  │
        │ - Handles background task execution │
        │ - Keeps loops alive across timeouts  │
        └─────────────────────────────────────┘
```

The system is designed to run completely natively on your machine without Docker. The FastAPI backend serves as the core orchestrator, and **the web UI fully controls the lifecycle of the entire system**, including dynamically spinning up the Temporal workflow engine on demand.

---

## Quick Start (The Streamlined Workflow)

### 1. Configure Credentials
Create a `.env` file in the root of your project directory. You only need your API key:
```env
GEMINI_API_KEY=your_actual_gemini_api_key_here
```

### 2. Start the Backend
Synchronize your dependencies and boot the FastAPI development server:
```bash
uv sync
make dev
```

### 3. Open the UI & Control Everything!
Open your browser and navigate to:
**`http://localhost:8001/ui/`**

From this single web dashboard, you can control the entire ecosystem:
- **Start Temporal:** Simply toggle the "Temporal Pipeline" switch in the left sidebar. The backend will automatically spin up the Temporal engine and workers in the background!
- **Temporal Dashboard:** Once toggled on, click the sidebar link to monitor live workflows (`http://localhost:8233`).
- **Design & Generate:** Submit design prompts and view real-time AI thoughts and pretty-printed plans in the console.
- **Run History:** Table showing past runs, allowing you to instantly **"Resume"** past chat sessions.

---

## Running Unit Tests
You can run the full, comprehensive unit test suite locally to verify that all endpoints, compilers, and Temporal integrations are completely green:
```bash
make test
```
