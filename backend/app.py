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
from backend.preview.routes import router as preview_router
from backend.primitives_read.routes import router as primitives_router
from backend.skills_read.routes import router as skills_router
from backend.web_search.routes import router as web_search_router

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
_OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "outputs"


def _warn_on_misconfiguration() -> None:
    """Print loud, unmissable warnings for the two silent-failure footguns.

    Both TEMPORAL_HOST and GEMINI_API_KEY are read via os.environ.get(..., "")
    somewhere downstream with NO error raised when empty — a design still
    "succeeds" (in-process geometry, or a late API-key failure deep in a
    replan), so a missing value here is otherwise invisible until someone
    notices Temporal's Web UI is empty or a run mysteriously fails.
    """
    if not os.environ.get("TEMPORAL_HOST", "").strip():
        print(
            "⚠️  TEMPORAL_HOST is not set — every design will run the geometry "
            "loop IN-PROCESS, not via Temporal. If you intended to use Temporal "
            "(e.g. you started the 'temporal' compose profile), designs will "
            "still generate and save to outputs/ but the Temporal Web UI "
            "(:8088) will show zero activity. Set TEMPORAL_HOST=temporal:7233 "
            "in .env (see .env.example)."
        )
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        print(
            "⚠️  GEMINI_API_KEY is not set — the planner/replanner/verifier will "
            "fail on the first real request. Set it in .env (see .env.example)."
        )


def create_app() -> FastAPI:
    """Create the FastAPI app with all backend services mounted."""
    _warn_on_misconfiguration()
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
        ForgeCAD studio iframe and deep-link into the Temporal Web UI without
        hardcoding URLs at build time.
        """
        return {
            "forgecad_studio_url": os.environ.get("FORGECAD_STUDIO_URL", ""),
            "backend_url": os.environ.get("BACKEND_URL", ""),
            "temporal_ui_url": os.environ.get("TEMPORAL_UI_URL", ""),
            "temporal_namespace": os.environ.get("TEMPORAL_NAMESPACE", "default"),
        }

    app.include_router(primitives_router)
    app.include_router(skills_router)
    app.include_router(preview_router)
    app.include_router(kb_router)
    app.include_router(web_search_router)
    app.include_router(designs_router)
    app.include_router(design_reference_router)

    # Read-only access to run artifacts (renders/STL/STEP) for the UI's Render /
    # Logs / Previous-Run views. NOTE: unauthenticated, consistent with the app.
    if _OUTPUTS_DIR.exists():
        app.mount("/outputs", StaticFiles(directory=str(_OUTPUTS_DIR)), name="outputs")

    # Serve the Product UI at /ui — same origin as the API, no CORS needed locally.
    if _FRONTEND_DIR.exists():
        app.mount("/ui", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")

    return app
