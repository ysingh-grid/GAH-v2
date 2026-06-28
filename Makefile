.PHONY: dev up down rebuild logs ps

# ── Dev (live reload — use this daily) ───────────────────────────────────────
# Source dirs are mounted directly into the container.
# Python changes → uvicorn --reload picks them up automatically.
# Skills / KB .md changes → visible immediately (read from disk at request time).
# Only run `make build` if pyproject.toml or uv.lock changed.
dev:
	docker compose --profile dev up

dev-temporal:
	docker compose --profile dev --profile temporal up

# ── Prod-like (full rebuild + restart) ────────────────────────────────────────
# Rebuilds the image from scratch and restarts all containers.
# Use when deps change or to verify the prod image is correct.
up:
	docker compose up --build

up-temporal:
	docker compose --profile temporal up --build

# ── Force full rebuild (no layer cache) ───────────────────────────────────────
rebuild:
	docker compose build --no-cache
	docker compose up -d

rebuild-temporal:
	docker compose --profile temporal build --no-cache
	docker compose --profile temporal up -d

# ── Stop everything ───────────────────────────────────────────────────────────
down:
	docker compose --profile temporal --profile dev --profile studio down --remove-orphans

# ── Helpers ───────────────────────────────────────────────────────────────────
logs:
	docker compose logs -f backend

ps:
	docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}" | grep -E "NAME|gah"
