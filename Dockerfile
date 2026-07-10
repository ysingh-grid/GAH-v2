# GAH v2 backend — Python 3.12 on Debian Bookworm slim
# CadQuery, MeshLib, VTK are large binaries; expect a 3–4 GB image.
#
# Build:  docker build -t gah-backend .
# Run:    docker run -p 8001:8001 --env-file .env gah-backend

FROM --platform=linux/amd64 python:3.12-slim-bookworm

# System libs needed by CadQuery (OCC), MeshLib, and VTK
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libgomp1 \
    libglu1-mesa \
    libxi6 \
    libxrender1 \
    libxext6 \
    xvfb \
    xauth \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install Python deps before copying source so this layer is cached on code changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Patch fast_rlm's engine so a Gemini call whose response BODY stalls cannot
# hang a planner turn for 40+ minutes (the openai client's timeout only covers
# the header phase — see patches/patch_fast_rlm_deadline.py for the measured
# evidence). Runs against the venv fast_rlm just installed; fails the BUILD
# loudly if a fast-rlm upgrade moved the anchor, so the hang can't silently
# come back.
COPY patches/ patches/
RUN uv run python patches/patch_fast_rlm_deadline.py

# Copy only what the runtime needs (tests and dev tooling excluded)
COPY backend/   backend/
COPY runtime/   runtime/
COPY rlm/       rlm/
COPY tools/     tools/
COPY primitives/ primitives/
COPY skills/    skills/
COPY KB/        KB/
COPY frontend/  frontend/
COPY temporal/  temporal/

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8001/health || exit 1

CMD ["uv", "run", "uvicorn", "backend.server:app", \
     "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
