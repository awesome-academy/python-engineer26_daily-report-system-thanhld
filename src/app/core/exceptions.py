"""Lỗi nghiệp vụ có mã và các exception handler trả về cùng một format JSON.

Format: {"error": {"code": "...", "message": "...", "details": ...}}
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)


class ErrorCode(StrEnum):
    BAD_REQUEST = "BAD_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    TOO_MANY_ATTEMPTS = "TOO_MANY_ATTEMPTS"
    CURRENT_PASSWORD_INCORRECT = "CURRENT_PASSWORD_INCORRECT"  # noqa: S105 (mã lỗi, không phải mật khẩu)
    EMAIL_ALREADY_EXISTS = "EMAIL_ALREADY_EXISTS"
    DEPARTMENT_CODE_ALREADY_EXISTS = "DEPARTMENT_CODE_ALREADY_EXISTS"
    DEPARTMENT_NOT_EMPTY = "DEPARTMENT_NOT_EMPTY"
    CANNOT_MODIFY_OWN_ACCOUNT = "CANNOT_MODIFY_OWN_ACCOUNT"
    USER_MANAGES_DEPARTMENTS = "USER_MANAGES_DEPARTMENTS"
    LAST_ACTIVE_ADMIN = "LAST_ACTIVE_ADMIN"
    USER_INACTIVE = "USER_INACTIVE"
    MANAGER_ROLE_REQUIRED = "MANAGER_ROLE_REQUIRED"
    REPORT_ALREADY_EXISTS = "REPORT_ALREADY_EXISTS"
    REPORT_DATE_OUT_OF_RANGE = "REPORT_DATE_OUT_OF_RANGE"
    INVALID_RECIPIENT = "INVALID_RECIPIENT"


class AppError(Exception):
    """Lỗi nghiệp vụ. Service ném lỗi này, handler chung đổi thành response JSON."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: ErrorCode = ErrorCode.BAD_REQUEST
    message: str = "Yêu cầu không hợp lệ."
    headers: Mapping[str, str] | None = None

    def __init__(
        self,
        message: str | None = None,
        *,
        code: ErrorCode | None = None,
        details: Any = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        super().__init__(self.message)


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = ErrorCode.UNAUTHORIZED
    message = "Bạn chưa đăng nhập hoặc phiên đăng nhập đã hết hạn."
    # Chuẩn OAuth2: response 401 báo client cách xác thực.
    headers = MappingProxyType({"WWW-Authenticate": "Bearer"})


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = ErrorCode.FORBIDDEN
    message = "Bạn không có quyền thực hiện thao tác này."


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = ErrorCode.NOT_FOUND
    message = "Không tìm thấy dữ liệu."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = ErrorCode.CONFLICT
    message = "Dữ liệu bị trùng."


class UnprocessableError(AppError):
    """Dữ liệu đúng định dạng nhưng vi phạm quy tắc nghiệp vụ (ví dụ gán manager sai role).

    Không có mã mặc định, lớp con phải tự đặt `code`: VALIDATION_ERROR có `details` là danh sách
    lỗi theo field, còn lỗi nghiệp vụ có `details` là dict, client cần mã riêng để phân biệt.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    message = "Dữ liệu không hợp lệ."

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.code in {AppError.code, ErrorCode.VALIDATION_ERROR}:
            msg = f"{cls.__name__} phải khai báo code riêng cho lỗi nghiệp vụ 422."
            raise TypeError(msg)


_HTTP_ERRORS: dict[int, tuple[ErrorCode, str]] = {
    status.HTTP_401_UNAUTHORIZED: (ErrorCode.UNAUTHORIZED, UnauthorizedError.message),
    status.HTTP_403_FORBIDDEN: (ErrorCode.FORBIDDEN, ForbiddenError.message),
    status.HTTP_404_NOT_FOUND: (ErrorCode.NOT_FOUND, "Không tìm thấy đường dẫn."),
    status.HTTP_405_METHOD_NOT_ALLOWED: (
        ErrorCode.METHOD_NOT_ALLOWED,
        "Phương thức HTTP không được hỗ trợ.",
    ),
}


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    """Body của mọi response lỗi: handler dùng để trả lỗi, Swagger dùng để mô tả lỗi."""

    error: ErrorBody


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """Khai báo response lỗi trên Swagger theo format chung, thay schema mặc định của FastAPI."""
    return {status_code: {"model": ErrorResponse} for status_code in status_codes}


def error_response(
    status_code: int,
    code: ErrorCode,
    message: str,
    details: Any = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(
        status_code=status_code, content=body.model_dump(mode="json"), headers=headers
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(part) for part in err["loc"]), "message": err["msg"]}
            for err in exc.errors()
        ]
        return error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.VALIDATION_ERROR,
            "Dữ liệu không hợp lệ.",
            details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _HTTP_ERRORS.get(exc.status_code, (ErrorCode.BAD_REQUEST, str(exc.detail)))
        return error_response(exc.status_code, code, message, headers=exc.headers)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", path=request.url.path, error=type(exc).__name__)
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            ErrorCode.INTERNAL_ERROR,
            "Hệ thống đang gặp sự cố, vui lòng thử lại sau.",
        )
