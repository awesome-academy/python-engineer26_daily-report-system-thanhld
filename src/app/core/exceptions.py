"""Lỗi nghiệp vụ có mã và các exception handler trả về cùng một format JSON.

Format: {"error": {"code": "...", "message": "...", "details": ...}}
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Self

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.constants import BYTES_PER_MB

logger = structlog.get_logger(__name__)

VALIDATION_ERROR_MESSAGE = "Dữ liệu không hợp lệ."


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
    NO_RECIPIENT_AVAILABLE = "NO_RECIPIENT_AVAILABLE"
    INVALID_MEMBER_CANDIDATE = "INVALID_MEMBER_CANDIDATE"
    EMPLOYEE_ROLE_REQUIRED = "EMPLOYEE_ROLE_REQUIRED"
    SETUP_TOKEN_INVALID = "SETUP_TOKEN_INVALID"  # noqa: S105 (mã lỗi, không phải mật khẩu)
    PASSWORD_ALREADY_SET = "PASSWORD_ALREADY_SET"  # noqa: S105 (mã lỗi, không phải mật khẩu)
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    IMPORT_VALIDATION_FAILED = "IMPORT_VALIDATION_FAILED"
    REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"


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


class ServiceUnavailableError(AppError):
    """Thành phần bên ngoài (Redis, hàng đợi task) đang lỗi: client thử lại sau."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = ErrorCode.SERVICE_UNAVAILABLE
    message = "Hệ thống tạm thời không xử lý được yêu cầu, vui lòng thử lại sau."


class UnprocessableError(AppError):
    """Dữ liệu đúng định dạng nhưng vi phạm quy tắc nghiệp vụ (ví dụ gán manager sai role).

    Không có mã mặc định, lớp con phải tự đặt `code`: VALIDATION_ERROR có `details` là danh sách
    lỗi theo field, còn lỗi nghiệp vụ có `details` là dict, client cần mã riêng để phân biệt.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    message = VALIDATION_ERROR_MESSAGE

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.code in {AppError.code, ErrorCode.VALIDATION_ERROR}:
            msg = f"{cls.__name__} phải khai báo code riêng cho lỗi nghiệp vụ 422."
            raise TypeError(msg)


class RequestTooLargeError(StarletteHTTPException):
    """Body của request vượt quá giới hạn chung (`BodySizeLimitMiddleware`).

    Là HTTPException của Starlette chứ không phải AppError: lỗi được ném ra lúc FastAPI đang đọc
    body, mà FastAPI chỉ để HTTPException đi qua, lỗi khác bị đổi thành 400.
    """

    def __init__(self, max_bytes: int) -> None:
        super().__init__(status.HTTP_413_CONTENT_TOO_LARGE)
        self.max_bytes = max_bytes

    def to_response(self) -> JSONResponse:
        return error_response(
            self.status_code,
            ErrorCode.REQUEST_TOO_LARGE,
            f"Dữ liệu gửi lên vượt quá dung lượng cho phép ({self.max_bytes / BYTES_PER_MB:g} MB).",
            {"max_bytes": self.max_bytes},
        )


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

    @classmethod
    def from_error(cls, exc: AppError) -> Self:
        return cls(error=ErrorBody(code=exc.code, message=exc.message, details=exc.details))


# Ví dụ trên Swagger cho lỗi validate (422) của mọi endpoint: details là danh sách field sai, tiền
# tố là vị trí của field (body, query, path).
_VALIDATION_ERROR_EXAMPLE = ErrorResponse(
    error=ErrorBody(
        code=ErrorCode.VALIDATION_ERROR,
        message=VALIDATION_ERROR_MESSAGE,
        details=[
            {
                "field": "body.email",
                "message": "value is not a valid email address: An email address must have an "
                "@-sign.",
            }
        ],
    )
)
# Lỗi chung khai bằng HTTP status: mọi endpoint trả cùng mã. Status khác (400, 409, 413…) chỉ có lỗi
# nghiệp vụ riêng của từng endpoint, phải khai bằng instance lỗi.
_COMMON_ERRORS: Mapping[int, ErrorResponse] = MappingProxyType(
    {
        status.HTTP_401_UNAUTHORIZED: ErrorResponse.from_error(UnauthorizedError()),
        status.HTTP_403_FORBIDDEN: ErrorResponse.from_error(ForbiddenError()),
        status.HTTP_404_NOT_FOUND: ErrorResponse.from_error(NotFoundError()),
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR_EXAMPLE,
        status.HTTP_503_SERVICE_UNAVAILABLE: ErrorResponse.from_error(ServiceUnavailableError()),
    }
)


def error_responses(*errors: int | AppError) -> dict[int | str, dict[str, Any]]:
    """Khai báo response lỗi trên Swagger theo format chung, kèm ví dụ cho từng lỗi.

    Mỗi phần tử là một ví dụ: instance lỗi nghiệp vụ endpoint có thể trả
    (`EmailAlreadyExistsError()`) cho ví dụ đúng mã, message, details như lúc chạy; HTTP status
    cho lỗi chung (`_COMMON_ERRORS`). Các ví dụ cùng status gộp vào một response, Swagger cho chọn
    từng ví dụ.
    """
    examples: dict[int, dict[str, dict[str, Any]]] = {}
    for error in errors:
        status_code, body = _error_example(error)
        value = body.model_dump(mode="json")
        status_examples = examples.setdefault(status_code, {})
        if any(example["value"] == value for example in status_examples.values()):
            msg = f"Ví dụ lỗi {body.error.code} của HTTP {status_code} bị khai hai lần."
            raise ValueError(msg)
        # Tên là mã lỗi, kèm field nếu có; hai lỗi khác nhau cùng tên (413 của file tải lên và của
        # nội dung giải nén) thì đánh số.
        base_name = _example_name(body.error)
        name, number = base_name, 1
        while name in status_examples:
            number += 1
            name = f"{base_name} ({number})"
        status_examples[name] = {"summary": name, "value": value}
    return {
        status_code: {
            "model": ErrorResponse,
            "content": {"application/json": {"examples": status_examples}},
        }
        for status_code, status_examples in examples.items()
    }


def _error_example(error: int | AppError) -> tuple[int, ErrorResponse]:
    if isinstance(error, AppError):
        return error.status_code, ErrorResponse.from_error(error)
    if error not in _COMMON_ERRORS:
        msg = f"HTTP {error} không có lỗi chung: truyền instance lỗi nghiệp vụ endpoint trả về."
        raise ValueError(msg)
    return error, _COMMON_ERRORS[error]


def _example_name(error: ErrorBody) -> str:
    # Cùng mã khác field (NOT_FOUND của user_id, department_id) thì tên ví dụ kèm field.
    field = error.details.get("field") if isinstance(error.details, dict) else None
    return f"{error.code}: {field}" if field else error.code


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
            VALIDATION_ERROR_MESSAGE,
            details,
        )

    @app.exception_handler(RequestTooLargeError)
    async def handle_request_too_large(_: Request, exc: RequestTooLargeError) -> JSONResponse:
        return exc.to_response()

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
