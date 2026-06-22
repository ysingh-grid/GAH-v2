#!/bin/bash

echo "Stopping all Docker services for GAH-v2..."
docker compose --profile temporal --profile studio down

echo "Starting all Docker services for GAH-v2 (Backend, Temporal, Worker, ForgeCAD Studio)..."
FORGECAD_STUDIO_URL=http://localhost:4000 docker compose --profile temporal --profile studio up -d --build

echo "All services are starting in the background. Use 'docker compose logs -f' to view logs."
