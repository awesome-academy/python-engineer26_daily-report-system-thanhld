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

    def __init__(self) -> None:
        super().__init__(details={"field": "current_password"})


class SetupTokenInvalidError(AppError):
    # Một lỗi chung cho token sai, đã dùng, hết hạn, tài khoản bị khóa hay đã có mật khẩu: không cho
    # dò token nào từng tồn tại. 400 thay vì 401: request này không dùng phiên đăng nhập.
    code = ErrorCode.SETUP_TOKEN_INVALID
    message = (
        "Link đặt mật khẩu không hợp lệ, đã được dùng hoặc đã hết hạn. "
        "Liên hệ quản trị viên để nhận link mới."
    )

    def __init__(self) -> None:
        super().__init__(details={"field": "token"})


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
