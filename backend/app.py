"""Builds the FastAPI application and mounts every service's router.

This is the ONE place services get wired together. Adding a new service =
add one include_router line here. Keeps routing out of server.py.
"""

from fastapi import FastAPI

from backend.primitives_read.routes import router as primitives_router
from backend.skills_read.routes import router as skills_router
from backend.web_search.routes import router as web_search_router


def create_app() -> FastAPI:
    """Create the FastAPI app with all backend services mounted."""
    app = FastAPI(title="GAH Backend", version="0.1.0")

    @app.get("/health")
    def health() -> dict:
        """Liveness check: is the backend up?"""
        return {"status": "ok", "version": "0.1.0"}

    app.include_router(primitives_router)
    app.include_router(skills_router)
    app.include_router(web_search_router)
    return app