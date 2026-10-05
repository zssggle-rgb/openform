from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, *, retryable: bool = False):
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable


def error_body(request: Request, code: str, message: str, *, retryable: bool = False) -> dict[str, Any]:
    return {"code": code, "message": message, "requestId": request.state.request_id,
            "retryable": retryable, "details": []}


async def api_error_handler(request: Request, error: ApiError) -> JSONResponse:
    return JSONResponse(error_body(request, error.code, error.message, retryable=error.retryable), status_code=error.status)
