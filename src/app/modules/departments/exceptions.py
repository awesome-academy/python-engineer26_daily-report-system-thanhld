from collections.abc import Sequence

from app.core.exceptions import ConflictError, ErrorCode, NotFoundError, UnprocessableError


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


class ManagerRoleRequiredError(UnprocessableError):
    code = ErrorCode.MANAGER_ROLE_REQUIRED
    message = "Chỉ gán được tài khoản có role MANAGER làm manager bộ phận."

    def __init__(self) -> None:
        super().__init__(details={"field": "user_id"})


class InvalidMemberCandidateError(UnprocessableError):
    code = ErrorCode.INVALID_MEMBER_CANDIDATE
    message = (
        "Chỉ thêm được nhân viên role USER đang hoạt động, chưa thuộc bộ phận nào. Lấy danh sách "
        "hợp lệ ở GET /manager/candidates; không ai được thêm khi còn id sai."
    )

    def __init__(self, invalid_ids: Sequence[int]) -> None:
        super().__init__(details={"field": "user_ids", "invalid_ids": list(invalid_ids)})


class EmployeeRoleRequiredError(UnprocessableError):
    code = ErrorCode.EMPLOYEE_ROLE_REQUIRED
    message = (
        "Manager chỉ gỡ được nhân viên role USER khỏi bộ phận; thành viên có role khác do admin "
        "xếp bộ phận."
    )

    def __init__(self) -> None:
        super().__init__(details={"field": "user_id"})
