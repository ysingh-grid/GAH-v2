#!/bin/bash
set -e

if [ ! -f .env ]; then
    echo "ERROR: .env not found. Run: cp .env.example .env, then set GEMINI_API_KEY." >&2
    exit 1
fi

echo "Stopping all Docker services for GAH-v2..."
docker compose --profile temporal --profile studio down

echo "Starting all Docker services for GAH-v2 (Backend, Temporal, Worker, ForgeCAD Studio)..."
# This script always runs the temporal profile, so TEMPORAL_HOST is forced
# here regardless of what's in .env — backend/designs/runner.py reads it once
# at import time; if it's empty, EVERY design silently runs in-process with
# zero error and zero Temporal Web UI activity. Don't rely on .env alone.
FORGECAD_STUDIO_URL=http://localhost:4000 \
TEMPORAL_HOST=temporal:7233 \
TEMPORAL_UI_URL=http://localhost:8088 \
  docker compose --profile temporal --profile studio up -d --build

echo "All services are starting in the background. Use 'docker compose logs -f' to view logs."
echo "Verify Temporal is actually wired in: docker exec gah-backend printenv TEMPORAL_HOST"
echo "  (must print 'temporal:7233' — if blank, designs run in-process, not via Temporal)"
