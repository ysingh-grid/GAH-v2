"""Builds the FastAPI application and mounts every service's router.

This is the ONE place services get wired together. Adding a new service =
add one include_router line here. Keeps routing out of server.py.
"""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.design_reference.routes import router as design_reference_router
from backend.designs.routes import router as designs_router
from backend.kb_read.routes import router as kb_router
from backend.primitives_read.routes import router as primitives_router
from backend.skills_read.routes import router as skills_router
from backend.web_search.routes import router as web_search_router
import json
import time

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
_OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "outputs"


def create_app() -> FastAPI:
    """Create the FastAPI app with all backend services mounted."""
    app = FastAPI(title="GAH Backend", version="0.1.0")

    # CORS — allow the frontend (any origin in dev, tightened in production via env).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        """Liveness check: is the backend up?"""
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/config")
    def config() -> dict:
        """Runtime config for the frontend.

        Reads env vars set by docker-compose so the frontend can embed the
        ForgeCAD studio iframe without hardcoding URLs at build time.
        """
        return {
            "forgecad_studio_url": os.environ.get("FORGECAD_STUDIO_URL", ""),
            "backend_url": os.environ.get("BACKEND_URL", ""),
        }

    @app.get("/api/runs")
    def list_runs() -> dict:
        """List all runs from the outputs directory."""
        runs = []
        if _OUTPUTS_DIR.exists():
            for d in _OUTPUTS_DIR.iterdir():
                if d.is_dir():
                    created_at = d.stat().st_ctime
                    status = "success" if (d / "solid.stl").exists() else "failed"
                    runs.append({
                        "run_id": d.name,
                        "created_at": created_at,
                        "status": status,
                    })
        runs.sort(key=lambda x: x["created_at"], reverse=True)
        return {"runs": runs}

    @app.get("/api/analytics")
    def get_analytics() -> dict:
        """Aggregate analytics from the outputs directory."""
        total = 0
        success = 0
        if _OUTPUTS_DIR.exists():
            for d in _OUTPUTS_DIR.iterdir():
                if d.is_dir():
                    total += 1
                    if (d / "solid.stl").exists():
                        success += 1
        return {
            "total_runs": total,
            "success_rate": f"{(success/total*100):.1f}%" if total > 0 else "0.0%",
            "successful_runs": success,
            "failed_runs": total - success
        }

    app.include_router(primitives_router)
    app.include_router(skills_router)
    app.include_router(kb_router)
    app.include_router(web_search_router)
    app.include_router(designs_router)
    app.include_router(design_reference_router)

    # Serve the Product UI at /ui — same origin as the API, no CORS needed locally.
    if _FRONTEND_DIR.exists():
        app.mount("/ui", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")

    return app