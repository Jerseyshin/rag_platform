from datetime import datetime, timezone
from enum import StrEnum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ErrorCode(StrEnum):
    INTERNAL_ERROR = "INTERNAL_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    FILE_TYPE_NOT_ALLOWED = "FILE_TYPE_NOT_ALLOWED"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    EMPTY_CONTENT = "EMPTY_CONTENT"
    PARSE_ENCRYPTED_PDF = "PARSE_ENCRYPTED_PDF"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    EMBEDDING_GATEWAY_503 = "EMBEDDING_GATEWAY_503"
    DB_TRANSIENT_ERROR = "DB_TRANSIENT_ERROR"
    SCHEDULER_ALREADY_RUNNING = "SCHEDULER_ALREADY_RUNNING"


class AppError(Exception):
    def __init__(
        self,
        detail: str,
        *,
        code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        status_code: int = 500,
    ) -> None:
        self.detail = detail
        self.code = code
        self.status_code = status_code


def error_payload(detail: str, code: ErrorCode) -> dict[str, str]:
    return {
        "detail": detail,
        "code": code.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(exc.detail, exc.code),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_payload(str(exc), ErrorCode.VALIDATION_ERROR),
        )

