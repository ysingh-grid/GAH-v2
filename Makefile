.PHONY: dev test clean help

dev:
	uv run uvicorn backend.server:app --host 0.0.0.0 --port 8001 --reload

test:
	uv run pytest

clean:
	rm -rf .pytest_cache .ruff_cache
	uv sync

help:
	@echo "Available commands:"
	@echo "  make dev    - Start the local FastAPI development server on port 8001 with hot-reload"
	@echo "  make test   - Run the full pytest test suite"
	@echo "  make clean  - Clear local caches and re-sync the python virtual environment"
