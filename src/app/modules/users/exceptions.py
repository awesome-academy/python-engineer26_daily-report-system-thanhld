from app.core.exceptions import ConflictError, ErrorCode


class EmailAlreadyExistsError(ConflictError):
    code = ErrorCode.EMAIL_ALREADY_EXISTS
    message = "Email đã được dùng cho một tài khoản khác."
