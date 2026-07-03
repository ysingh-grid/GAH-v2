
# GAH-v2 — Geometry Agent Harness

A multi-milestone AI-powered CAD design system: natural language → design plan → 3D geometry → ForgeCAD Studio rendering.

**Current milestone:** M11 (Temporal durability for geometry pipeline).

## Architecture

```
┌─────────────────────────────────────────────┐
│  Frontend: /ui/                             │
│  - Hero page + FAB overlay                  │
│  - Design panel (WebSocket chat)            │
│  - ForgeCAD Studio iframe (live preview)    │
└──────────────┬──────────────────────────────┘
               │
        ┌──────▼──────┐
        │ WebSocket   │
        │ /designs    │
        └──────┬──────┘
               │
    ┌──────────▼──────────────┐
    │ backend/designs/runner   │
    │ - Planner turn (RLM)     │
    │ - Geometry loop          │
    │ - ForgeCAD compile       │
    └──────────┬───────────────┘
               │
    ┌──────────▼──────────────────┐
    │ Temporal (optional)          │
    │ - DesignWorkflow            │
    │ - Activities (geo + forge)   │
    │ - Worker pool               │
    └──────────────────────────────┘
```

**Components:**

- **`backend/`** — FastAPI service (:8001)
  - `designs/` — WebSocket + Temporal client (forked on `TEMPORAL_HOST`)
  - `primitives_read/` — Read-only primitive library
  - `skills_read/` — Read-only skill guides
- **`frontend/`** — Static HTML/CSS/JS (served at `/ui/`)
- **`runtime/`** — Pure business logic (no Temporal)
  - `planner` — fast-rlm integration
  - `loop` — geometry validation loop
  - `compile_forge` — plan → `.forge.js`
- **`temporal/`** — Job scheduler
  - `activities` — sync geometry + forge compile tasks
  - `workflow` — orchestration logic
  - `worker` — task executor
- **`tools/`** — Low-level wrappers (CadQuery, mesh, render)

## Quick Start

### 1. Prerequisites

```bash
# Python 3.12+
uv sync

# Optional: Gemini API key for planner
# https://aistudio.google.com/app/apikeys
echo 'GEMINI_API_KEY=your_key_here' > .env
```

### 2. Backend only (in-process geometry)

```bash
# Terminal 1: Backend
uv run uvicorn backend.server:app --host 0.0.0.0 --port 8001

# Visit http://localhost:8001/ui/
# Geometry loop runs in-process (no Temporal)
```

### 3. With Temporal durability (crash-safe geometry)

```bash
docker compose --profile temporal up
```

Check Temporal Web UI: http://localhost:8088

### 4. With ForgeCAD Studio live preview

```bash
# Start all services with profiles
FORGECAD_STUDIO_URL=http://localhost:4000 docker compose --profile temporal --profile studio up
```

> **Tip:** You can also use the included `./restart.sh` script to stop, build, and restart all Docker services for this project in the background automatically.

Frontend auto-discovers Studio URL via `/config` endpoint.

## Environment Variables

```env
# Required
GEMINI_API_KEY=your_gemini_api_key

# Optional
TEMPORAL_HOST=localhost:7233           # Enable Temporal path; empty = in-process
TEMPORAL_NAMESPACE=default             # Temporal namespace
TEMPORAL_TASK_QUEUE=design             # Task queue name
FORGECAD_STUDIO_URL=http://localhost:4000  # Studio URL for iframe
BACKEND_URL=http://localhost:8001      # Backend for frontend discovery
```

## API

### `/config` (GET)

Frontend discovers runtime URLs:

```json
{
  "forgecad_studio_url": "http://localhost:4000",
  "backend_url": "http://localhost:8001"
}
```

### `POST /designs`

Create session:

```json
{"design_id": "des_abc123..."}
```

### `WS /designs/{id}/chat`

Client sends:

```json
{"type": "message", "text": "make a cube"}
```

Server sends events:

```json
{"type": "thinking"}
{"type": "generating", "stage": "cadquery_compile"}
{"type": "success", "forge_js": "...", "run_id": "...", "plan": {...}}
{"type": "failed", "category": "...", "message": "..."}
{"type": "needs_user", "question": "...", "options": [...]}
```

## Testing

```bash
# All tests (163 pass)
uv run pytest

# Temporal tests only (26 tests)
uv run pytest tests/test_temporal.py -v

# Backend API tests
uv run pytest tests/test_backend_designs.py -v
```

## Docker

```bash
# Build
docker build -t gah-backend:latest .

# Compose (all-in-one with optional profiles)
docker compose up                           # Backend only
docker compose --profile temporal up        # + Temporal + worker
docker compose --profile studio up          # + ForgeCAD Studio
docker compose --profile temporal --profile studio up  # All three

# Check health
curl http://localhost:8001/health
curl http://localhost:8088  # Temporal Web UI (with --profile temporal)
```

Platform: x86_64 only (Apple Silicon: `--platform=linux/amd64`).

## Geometry Pipeline

**With Temporal (recommended):**

```
Client send "make a cube"
    ↓
Backend POST /designs → WS /designs/{id}/chat
    ↓
run_chat_turn (planner + fork decision)
    ↓
_USE_TEMPORAL=True? → execute DesignWorkflow
    ↓
Activity 1: run_geometry_activity (10 min timeout, no retry)
    - CadQuery compile + MeshLib verify + replan loop
    ↓
If success: Activity 2: compile_forge_activity (2 min, 2 retries)
    - plan → .forge.js
    ↓
DesignResult → WS success event
```

**In-process (no Temporal):**

```
Client send "make a cube"
    ↓
run_chat_turn (planner + fork decision)
    ↓
_USE_TEMPORAL=False? → executor thread pool
    ↓
run_geometry_loop + compile_plan_to_forge
    ↓
LoopResult → WS success event
```

Switch via `TEMPORAL_HOST` env var. Empty string = in-process. Any value = Temporal.

## Development

### Adding a new primitive

1. Edit `primitives/library.json` — add `{name, params, verify_steps, cadquery_template}`
2. Run tests: `uv run pytest tests/test_schema.py -k primitive`
3. Planner auto-discovers via `/internal/primitives/list`

### Modifying the workflow

1. Edit `temporal/workflow.py` — activity calls, timeouts, retries
2. Sync activities in `temporal/activities.py`
3. Test: `uv run pytest tests/test_temporal.py -v`
4. Deploy: `docker compose --profile temporal up`

### New skill guide

1. Create `skills/my_skill.md` — markdown reasoning guide
2. Add to `skills/SKILLS.md` index
3. Planner loads on demand: `read_skill("my_skill")`

## Project Structure

```
artifacts/                  # STEP, STL, .forge.js, traces, renders
backend/
  app.py                    # FastAPI + static /ui/ + /health + /config
  designs/
    runner.py               # run_chat_turn orchestrator (Temporal fork)
    models.py               # DesignSession
    routes.py               # WebSocket + POST /designs
  primitives_read/
    store.py, routes.py     # Read primitive library
  skills_read/
    store.py, routes.py     # Read skill guides
frontend/
  index.html                # FAB + panel overlay
  app.js                    # window.__gah interface
  style.css                 # CSS variables + animations
primitives/
  library.json              # 20 solid primitive specs
runtime/
  schema.py                 # PrimitivePlan + validate
  planner.py                # fast-rlm wrapper
  loop.py                   # Geometry validation loop
  compile_forge.py          # plan → .forge.js
temporal/
  shared.py                 # DesignInput/DesignResult dataclasses
  activities.py             # run_geometry_activity, compile_forge_activity
  workflow.py               # DesignWorkflow orchestration
  client.py                 # Temporal client factory
  worker.py                 # Worker entry point
  __init__.py
tools/
  render_views.py           # 3D renders (matplotlib + VTK)
  artifacts.py              # STEP/STL/trace I/O
  ...
tests/
  test_temporal.py          # 26 Temporal tests
  test_backend_designs.py   # WebSocket + runner tests
  test_*.py                 # ~160 tests total
rlm/                        # fast-rlm config + pull tools
skills/                     # Reasoning guides for planner
Dockerfile                  # Multi-stage x86_64 image
docker-compose.yml          # Backend, Temporal, Studio, Worker
pyproject.toml              # uv, pytest, ruff, mypy config
.env.example                # Template (commit, copy to .env)
```

## Troubleshooting

**"Cannot reach backend"**
- Backend on 8001? `curl http://localhost:8001/health`
- CORS issues? Frontend at `/ui/`, backend at `/`

**"Temporal not connecting"**
- Worker at `TEMPORAL_HOST=localhost:7233`?
- Temporal server running? `curl http://localhost:8088`
- Task queue mismatch? Check `TEMPORAL_TASK_QUEUE` env (default: `design`)

**"ForgeCAD Studio not loading"**
- Set `FORGECAD_STUDIO_URL` before backend start
- Studio on 4000? `curl http://localhost:4000`
- Frontend fetches `/config` at boot — check Network tab

**Tests fail: "mypy: ignore-errors"**
- `rlm/pull_tools.py` has type suppressions (fast-rlm SDK issues)
- See `# mypy: ignore-errors` comment in file

## Milestones

- **M1–M7:** Geometry pipeline, CadQuery/MeshLib, ForgeCAD compile
- **M8:** WebSocket chat API, designs service
- **M9:** Frontend overlay (FAB + panel), M8 API wiring
- **M10:** Docker + `/config` endpoint
- **M11:** Temporal durability wrapper (current)

Next: Scale to production, multi-user sessions, design library.
