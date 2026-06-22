from typing import Any, Optional

from pydantic import BaseModel, Field


class ErrorPayload(BaseModel):
    code: str
    message: str


class ApiResponse(BaseModel):
    ok: bool
    tool: str
    data: Optional[Any] = None
    error: Optional[ErrorPayload] = None
    run_id: Optional[str] = None
    trace_id: Optional[str] = None


class ReadSkillRequest(BaseModel):
    skill_name: str


class ScanRepoRequest(BaseModel):
    path: str = "."
    max_depth: int = 4
    include_extensions: list[str] = Field(
        default_factory=lambda: [".py", ".md", ".json", ".yaml", ".yml"]
    )
    exclude_dirs: list[str] = Field(
        default_factory=lambda: [
            ".git",
            "__pycache__",
            ".venv",
            "node_modules",
            "output",
            "outputs",
            "generated",
        ]
    )


class ReadFileRequest(BaseModel):
    path: str


class WriteFileRequest(BaseModel):
    path: str
    content: str
    overwrite: bool = True


class ListDirRequest(BaseModel):
    path: str = "."


class RunPipelineRequest(BaseModel):
    pipeline_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 60
    run_id: Optional[str] = None


class ExecuteToolRequest(BaseModel):
    tool_name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    run_id: Optional[str] = None


class InspectOutputRequest(BaseModel):
    path: str
    inspection_type: str = "file_metadata"


class SaveTraceRequest(BaseModel):
    run_id: str
    step: int
    event_type: str
    tool_name: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None


class GetTraceRequest(BaseModel):
    run_id: str
