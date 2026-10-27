from app.core.exceptions import ErrorCode, UnauthorizedError


class InvalidCredentialsError(UnauthorizedError):
    code = ErrorCode.INVALID_CREDENTIALS
    message = "Email hoặc mật khẩu không đúng."
