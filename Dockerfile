# GAH v2 backend — Python 3.12 on Debian Bookworm slim
# CadQuery, MeshLib, VTK are large binaries; expect a 3–4 GB image.
#
# Build:  docker build -t gah-backend .
# Run:    docker run -p 8001:8001 --env-file .env gah-backend

FROM python:3.12-slim-bookworm

# System libs needed by CadQuery (OCC), MeshLib, and VTK
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libgomp1 \
    libglu1-mesa \
    libxi6 \
    libxrender1 \
    libxext6 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install Python deps before copying source so this layer is cached on code changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy only what the runtime needs (tests and dev tooling excluded)
COPY backend/   backend/
COPY runtime/   runtime/
COPY rlm/       rlm/
COPY tools/     tools/
COPY primitives/ primitives/
COPY skills/    skills/
COPY frontend/  frontend/

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8001/health || exit 1

CMD ["uv", "run", "uvicorn", "backend.server:app", \
     "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
