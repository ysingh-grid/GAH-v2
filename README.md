# GAH-v2 - Local AI Geometry Agent Harness

GAH-v2 is a local AI CAD pipeline. The web UI accepts natural-language design
requests, streams the RLM/runtime trace, generates CadQuery geometry, verifies
outputs, and stores every run under `artifacts/{run_id}`.

## Quick Start

```bash
uv sync --extra dev
make dev
```

Open:

```text
http://localhost:8001/ui/
```

The intended local-dev model is one terminal command for the FastAPI backend,
then browser control for the rest:

- Start/stop Temporal from the UI sidebar.
- Restart the backend-managed Temporal worker from the System page.
- View Temporal worker/server logs from the System page.
- Watch live RLM/runtime events in the Live Agent Trace panel.
- Open run history to inspect timelines, trace JSON, STL, and STEP artifacts.

## Configuration

Create `.env` in the repo root:

```env
GEMINI_API_KEY=your_actual_gemini_api_key_here
```

Optional local settings:

```env
BACKEND_URL=http://localhost:8001
TEMPORAL_ADDRESS=localhost:7233
TEMPORAL_HOST=localhost:7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=design
FORGECAD_STUDIO_URL=http://localhost:4000
```

## Runtime Controls

The backend serves the UI and APIs on port `8001`.

Temporal mode requires the Temporal CLI:

```bash
brew install temporal
```

The UI calls `POST /temporal/start`, which starts:

- Temporal dev server on `localhost:7233`
- Temporal UI on `http://localhost:8233`
- Python worker on task queue `design`

If a worker crashes or stale code is suspected, use System -> Restart Worker.
The System page also shows recent worker errors from `logs/temporal_worker.log`.

## Traces, Logs, And Artifacts

Each run writes durable evidence under:

```text
artifacts/{run_id}/
```

Important files:

- `events.jsonl` - normalized live timeline events for frontend replay.
- `trace.json` - final structured runtime trace.
- `solid.stl` / `solid.step` - generated geometry outputs.
- `threeview.png` - rendered verification image when produced.

General logs live under:

```text
logs/
```

Fast-RLM logs are ingested into per-run `events.jsonl` when the planner returns
a `log_file`.

## ForgeCAD Status

ForgeCAD is currently treated as an optional STL preview surface. The UI label
is intentionally `ForgeCAD STL Preview`.

The editable ForgeCAD handoff is not complete until the runtime emits `.forge.js`
directly from `PrimitivePlan` and gates it with ForgeCAD's 3D compare command.
STEP/STL remains the current geometry output.

## Verification

Run all tests:

```bash
make test
```

Run lint:

```bash
uv run ruff check .
```

Run strict type checks after dev dependencies are installed:

```bash
uv run mypy backend runtime temporal tools tests
```
