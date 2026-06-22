from fastapi import APIRouter

from backend.config import settings
from backend.schemas import (
    ExecuteToolRequest,
    GetTraceRequest,
    InspectOutputRequest,
    ListDirRequest,
    ReadFileRequest,
    ReadSkillRequest,
    RunPipelineRequest,
    SaveTraceRequest,
    ScanRepoRequest,
    WriteFileRequest,
)
from backend.services import file_service, inspection_service, pipeline_service, repo_service, skill_service, tool_registry, trace_service
from backend.utils.response import BridgeError, error_response, ok_response

router = APIRouter()


def _handle(tool: str, func, *args, run_id: str | None = None, **kwargs):
    try:
        return ok_response(tool, func(*args, **kwargs), run_id=run_id)
    except BridgeError as exc:
        return error_response(tool, exc.code, exc.message, run_id=run_id)
    except Exception as exc:
        return error_response(tool, "BACKEND_ERROR", str(exc), run_id=run_id)


@router.get("/health")
def health():
    return ok_response(
        "health",
        {
            "status": "up",
            "project_root": str(settings.project_root),
            "skills_dir_exists": settings.skills_dir.exists(),
            "output_dir_exists": settings.output_dir.exists(),
        },
    )


@router.post("/list-skills")
def list_skills():
    return _handle("list_skills", skill_service.list_skills)


@router.post("/read-skill")
def read_skill(request: ReadSkillRequest):
    return _handle("read_skill", skill_service.read_skill, request.skill_name)


@router.post("/scan-repo")
def scan_repo(request: ScanRepoRequest):
    return _handle(
        "scan_repo",
        repo_service.scan_repo,
        request.path,
        request.max_depth,
        request.include_extensions,
        request.exclude_dirs,
    )


@router.post("/read-file")
def read_file(request: ReadFileRequest):
    return _handle("read_file", file_service.read_file, request.path)


@router.post("/write-file")
def write_file(request: WriteFileRequest):
    return _handle("write_file", file_service.write_file, request.path, request.content, request.overwrite)


@router.post("/list-dir")
def list_dir(request: ListDirRequest):
    return _handle("list_dir", file_service.list_dir, request.path)


@router.post("/run-pipeline")
def run_pipeline(request: RunPipelineRequest):
    return _handle(
        "run_pipeline",
        pipeline_service.run_pipeline,
        request.pipeline_name,
        request.args,
        request.timeout_seconds,
        run_id=request.run_id,
    )


@router.post("/execute-tool")
def execute_tool(request: ExecuteToolRequest):
    return _handle("execute_tool", tool_registry.execute_tool, request.tool_name, request.payload, run_id=request.run_id)


@router.post("/inspect-output")
def inspect_output(request: InspectOutputRequest):
    return _handle("inspect_output", inspection_service.inspect_output, request.path, request.inspection_type)


@router.post("/save-trace")
def save_trace(request: SaveTraceRequest):
    event = request.model_dump()
    return _handle("save_trace", trace_service.save_trace, request.run_id, event, run_id=request.run_id)


@router.post("/get-trace")
def get_trace(request: GetTraceRequest):
    return _handle("get_trace", trace_service.get_trace, request.run_id, run_id=request.run_id)
