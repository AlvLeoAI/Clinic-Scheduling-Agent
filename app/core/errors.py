from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from app.schemas.foundation import ErrorDetail, ErrorResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False):
        self.status, self.code, self.message, self.retryable = status, code, message, retryable


def error_response(
    request: Request, status: int, code: str, message: str, retryable: bool = False
) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", str(uuid4()))
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, retryable=retryable), trace_id=trace_id
    )
    headers = {"X-Trace-ID": trace_id}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers=headers)
