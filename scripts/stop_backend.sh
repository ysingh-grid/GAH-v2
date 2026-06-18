#!/usr/bin/env bash
set -euo pipefail

PORT="${DTCM_BACKEND_PORT:-8001}"
PID="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN || true)"

if [[ -z "${PID}" ]]; then
  echo "No backend bridge is listening on port ${PORT}"
  exit 0
fi

echo "Stopping backend bridge on port ${PORT}: PID ${PID}"
kill ${PID}
