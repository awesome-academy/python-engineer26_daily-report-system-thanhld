from app.core.exceptions import ConflictError, ErrorCode, NotFoundError


class DepartmentNotFoundError(NotFoundError):
    message = "Không tìm thấy bộ phận."

    def __init__(self) -> None:
        super().__init__(details={"field": "department_id"})


class DepartmentCodeExistsError(ConflictError):
    code = ErrorCode.DEPARTMENT_CODE_ALREADY_EXISTS
    message = "Mã bộ phận đã được dùng cho một bộ phận khác."

    def __init__(self) -> None:
        super().__init__(details={"field": "code"})


class DepartmentNotEmptyError(ConflictError):
    code = ErrorCode.DEPARTMENT_NOT_EMPTY
    message = "Bộ phận còn thành viên. Chuyển hoặc gỡ hết thành viên trước khi xóa."

    def __init__(self, member_count: int) -> None:
        super().__init__(details={"member_count": member_count})
