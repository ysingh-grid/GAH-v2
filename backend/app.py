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

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


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