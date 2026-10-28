import math

from fastapi import status

from app.core.exceptions import AppError, ErrorCode, UnauthorizedError


class InvalidCredentialsError(UnauthorizedError):
    code = ErrorCode.INVALID_CREDENTIALS
    message = "Email hoặc mật khẩu không đúng."


class CurrentPasswordIncorrectError(AppError):
    # 400 thay vì 401: client không được hiểu nhầm là phiên đăng nhập hết hạn rồi đăng xuất.
    code = ErrorCode.CURRENT_PASSWORD_INCORRECT
    message = "Mật khẩu hiện tại không đúng."


class TooManyAttemptsError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = ErrorCode.TOO_MANY_ATTEMPTS

    def __init__(self, *, retry_after: int) -> None:
        minutes = math.ceil(retry_after / 60)
        super().__init__(
            f"Bạn đã đăng nhập sai quá nhiều lần. Vui lòng thử lại sau {minutes} phút."
        )
        # Chuẩn HTTP: báo client số giây cần chờ trước khi thử lại.
        self.headers = {"Retry-After": str(retry_after)}
