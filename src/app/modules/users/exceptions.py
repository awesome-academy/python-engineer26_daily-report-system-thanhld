from app.core.exceptions import (
    AppError,
    ConflictError,
    ErrorCode,
    NotFoundError,
    UnprocessableError,
)


class EmailAlreadyExistsError(ConflictError):
    code = ErrorCode.EMAIL_ALREADY_EXISTS
    message = "Email đã được dùng cho một tài khoản khác."


class UserNotFoundError(NotFoundError):
    message = "Người dùng không tồn tại hoặc đã bị xóa."

    def __init__(self) -> None:
        super().__init__(details={"field": "user_id"})


class CannotModifyOwnAccountError(AppError):
    # Admin tự khóa, tự xóa hay tự hạ role thì mất quyền quản trị ngay, có thể không còn admin nào.
    code = ErrorCode.CANNOT_MODIFY_OWN_ACCOUNT
    message = "Không thể tự khóa, tự xóa hoặc tự đổi role của tài khoản đang đăng nhập."

    def __init__(self, field: str | None = None) -> None:
        super().__init__(details={"field": field} if field else None)


class UserManagesDepartmentsError(ConflictError):
    code = ErrorCode.USER_MANAGES_DEPARTMENTS
    message = (
        "Người dùng đang là manager của bộ phận. Gỡ khỏi các bộ phận đó trước khi đổi role, "
        "khóa hoặc xóa."
    )


class LastActiveAdminError(ConflictError):
    code = ErrorCode.LAST_ACTIVE_ADMIN
    message = (
        "Phải còn ít nhất một admin đang hoạt động; không thể khóa, hạ role hoặc xóa admin này."
    )


class UserInactiveError(UnprocessableError):
    code = ErrorCode.USER_INACTIVE
    message = "Tài khoản đang bị khóa, mở khóa trước khi thực hiện thao tác này."

    def __init__(self) -> None:
        super().__init__(details={"field": "user_id"})
