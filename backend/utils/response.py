from typing import Any

from backend.schemas import ApiResponse, ErrorPayload


class BridgeError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def ok_response(
    tool: str,
    data: Any = None,
    run_id: str | None = None,
    trace_id: str | None = None,
) -> ApiResponse:
    return ApiResponse(ok=True, tool=tool, data=data, error=None, run_id=run_id, trace_id=trace_id)


def error_response(
    tool: str,
    code: str,
    message: str,
    run_id: str | None = None,
    trace_id: str | None = None,
) -> ApiResponse:
    return ApiResponse(
        ok=False,
        tool=tool,
        data=None,
        error=ErrorPayload(code=code, message=message),
        run_id=run_id,
        trace_id=trace_id,
    )
