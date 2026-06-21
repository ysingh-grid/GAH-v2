from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.config import settings
from backend.routes.internal import router as internal_router
from backend.utils.response import error_response

settings.ensure_directories()

app = FastAPI(title="RLM Backend Bridge", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(internal_router, prefix="/internal")


_PATH_TO_TOOL = {
    "/internal/list-skills": "list_skills",
    "/internal/read-skill": "read_skill",
    "/internal/scan-repo": "scan_repo",
    "/internal/read-file": "read_file",
    "/internal/write-file": "write_file",
    "/internal/list-dir": "list_dir",
    "/internal/run-pipeline": "run_pipeline",
    "/internal/execute-tool": "execute_tool",
    "/internal/inspect-output": "inspect_output",
    "/internal/save-trace": "save_trace",
    "/internal/get-trace": "get_trace",
}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    tool = _PATH_TO_TOOL.get(request.url.path, "validation")
    message = "; ".join(error.get("msg", "Invalid request") for error in exc.errors())
    return JSONResponse(
        status_code=200,
        content=error_response(tool, "INVALID_REQUEST", message).model_dump(),
    )
