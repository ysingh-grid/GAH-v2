# GAH-v2

## RLM Backend Bridge

This project includes a FastAPI backend bridge that lets a sandboxed RLM runtime use safe HTTP tools instead of touching the filesystem directly.

Start the backend from this directory:

```bash
export DTCM_PROJECT_ROOT=$(pwd)
uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload
```

Or use the project script:

```bash
bash scripts/start_backend.sh
```

Stop the backend:

```bash
bash scripts/stop_backend.sh
```

Useful checks:

```bash
curl http://localhost:8001/internal/health
curl -X POST http://localhost:8001/internal/list-skills -H "Content-Type: application/json" -d '{}'
curl -X POST http://localhost:8001/internal/read-skill -H "Content-Type: application/json" -d '{"skill_name":"overview"}'
curl -X POST http://localhost:8001/internal/scan-repo -H "Content-Type: application/json" -d '{"path":".","max_depth":3}'
```

The RLM-side bridge lives in `rlm/tools.py` and calls `DTCM_BACKEND_URL`, defaulting to `http://localhost:8001`.

To test what the RLM sandbox-facing bridge can fetch through the backend:

```bash
python scripts/rlm_backend_smoke.py
```

That smoke test calls only `rlm/tools.py`, then verifies skill discovery, skill reads, repo scan, safe file write, output inspection, allowlisted pipelines, allowlisted tool execution, blocked `.env` reads, and trace save/get.

To run the actual `fast_rlm` runtime with only backend bridge tools exposed:

```bash
export GEMINI_API_KEY=...
python scripts/run_full_rlm_backend_demo.py
```

While it runs, the backend terminal should show `/internal/*` requests from the RLM tool calls.
