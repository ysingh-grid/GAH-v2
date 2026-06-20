"""Entrypoint: expose the ASGI `app` and run it on :8001 with uvicorn."""

import uvicorn

from backend.app import create_app

app = create_app()  # uvicorn imports this object: `uvicorn backend.server:app`

if __name__ == "__main__":
    uvicorn.run("backend.server:app", host="127.0.0.1", port=8001, reload=True)
