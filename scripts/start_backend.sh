#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
export DTCM_PROJECT_ROOT="${DTCM_PROJECT_ROOT:-$(pwd)}"
export DTCM_BACKEND_HOST="${DTCM_BACKEND_HOST:-0.0.0.0}"
export DTCM_BACKEND_PORT="${DTCM_BACKEND_PORT:-8001}"

if python - <<'PY'
import os
import sys
import urllib.request

port = os.getenv("DTCM_BACKEND_PORT", "8001")
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/internal/health", timeout=1) as response:
        if response.status == 200:
            sys.exit(0)
except Exception:
    sys.exit(1)
PY
then
  echo "Backend bridge is already running at http://localhost:${DTCM_BACKEND_PORT}"
  echo "Run: python scripts/rlm_backend_smoke.py"
  echo "Run actual fast_rlm demo after setting GEMINI_API_KEY: python scripts/run_full_rlm_backend_demo.py"
  exit 0
fi

python -m uvicorn backend.main:app --host "${DTCM_BACKEND_HOST}" --port "${DTCM_BACKEND_PORT}"
