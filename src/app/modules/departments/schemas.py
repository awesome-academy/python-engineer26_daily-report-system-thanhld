import re
from datetime import datetime
from typing import Annotated, Any

from fastapi import Query
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from app.core import messages
from app.core.constants import (
    DEPARTMENT_CODE_MAX_LENGTH,
    DEPARTMENT_CODE_MIN_LENGTH,
    DEPARTMENT_CODE_PATTERN,
    DEPARTMENT_DESCRIPTION_MAX_LENGTH,
    DEPARTMENT_MEMBERS_ADD_MAX,
    DEPARTMENT_MEMBERS_ADD_MIN,
    DEPARTMENT_NAME_MAX_LENGTH,
    DEPARTMENT_NAME_MIN_LENGTH,
)
from app.core.pagination import PageParams
from app.core.validators import Id, Keyword, NoNul, blank_to_none, drop_duplicates, reject_null
from app.modules.users.models import UserRole
from app.seed_data import (
    EXAMPLE_DEPARTMENT,
    EXAMPLE_EMPLOYEE,
    EXAMPLE_MANAGER,
    EXAMPLE_NEW_USER,
    EXAMPLE_NEW_USER_ID,
    seed_id,
)


def _check_department_code(code: str) -> str:
    # Kiểm tra trước khi chuyển chữ hoa: upper() đổi ngầm ký tự Unicode ("ß" thành "SS", chữ i
    # không chấm U+0131 thành "I"), vừa lách quy tắc chữ không dấu, vừa làm mã dài hơn max_length
    # đã kiểm tra (DB báo lỗi, API trả 500).
    if not re.fullmatch(DEPARTMENT_CODE_PATTERN, code):
        raise ValueError(messages.DEPARTMENT_CODE_INVALID)
    return code


# Mã chuẩn hóa về chữ hoa, nên " dev " và "DEV" là một mã. Chỉ ASCII nên upper() không đổi độ dài.
DepartmentCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=DEPARTMENT_CODE_MIN_LENGTH,
        max_length=DEPARTMENT_CODE_MAX_LENGTH,
    ),
    AfterValidator(_check_department_code),
    AfterValidator(str.upper),
]
DepartmentName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=DEPARTMENT_NAME_MIN_LENGTH,
        max_length=DEPARTMENT_NAME_MAX_LENGTH,
    ),
    NoNul,
]
DepartmentDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=DEPARTMENT_DESCRIPTION_MAX_LENGTH),
    NoNul,
    AfterValidator(blank_to_none),
]


# Ví dụ trên Swagger: bộ phận, manager, nhân viên của dữ liệu seed (app.seed_data).
_DEPARTMENT_EXAMPLE: dict[str, Any] = {
    "id": seed_id(EXAMPLE_DEPARTMENT),
    "code": EXAMPLE_DEPARTMENT.code,
    "name": EXAMPLE_DEPARTMENT.name,
    "description": EXAMPLE_DEPARTMENT.description,
    "created_at": "2026-10-26T02:00:00Z",
    "updated_at": "2026-10-26T02:00:00Z",
}
_MANAGER_EXAMPLE: dict[str, Any] = {
    "id": seed_id(EXAMPLE_MANAGER),
    "email": EXAMPLE_MANAGER.email,
    "full_name": EXAMPLE_MANAGER.full_name,
    "assigned_at": "2026-10-26T02:00:00Z",
}


class DepartmentOut(BaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_extra={"examples": [_DEPARTMENT_EXAMPLE]}
    )

    id: int
    code: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class DepartmentCreate(BaseModel):
    # Field lạ trả 422 như DepartmentUpdate, để client biết dữ liệu đó không được lưu.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "code": "MKT",
                    "name": "Phòng Marketing",
                    "description": "Truyền thông và quảng bá sản phẩm",
                }
            ]
        },
    )

    code: DepartmentCode
    name: DepartmentName
    description: DepartmentDescription | None = None


class DepartmentUpdate(BaseModel):
    """Cập nhật từng phần: field không gửi thì giữ nguyên, `null` xóa mô tả.

    Field lạ bị từ chối (422) thay vì bỏ qua, để client biết thay đổi đó không có hiệu lực.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"name": "Phòng Truyền thông", "description": "Truyền thông nội bộ và đối ngoại"}
            ]
        },
    )

    code: DepartmentCode | None = None
    name: DepartmentName | None = None
    description: DepartmentDescription | None = None

    _not_null = field_validator("code", "name")(reject_null)


class DepartmentListParams(PageParams):
    keyword: Keyword | None = None


DepartmentListQuery = Annotated[DepartmentListParams, Query()]


class DepartmentMemberListParams(PageParams):
    keyword: Annotated[
        Keyword | None, Field(description="Tìm theo họ tên (không dấu) hoặc email")
    ] = None


DepartmentMemberListQuery = Annotated[DepartmentMemberListParams, Query()]


class DepartmentMemberOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": seed_id(EXAMPLE_EMPLOYEE),
                    "email": EXAMPLE_EMPLOYEE.email,
                    "full_name": EXAMPLE_EMPLOYEE.full_name,
                    "role": EXAMPLE_EMPLOYEE.role,
                    "is_active": True,
                    "is_manager": False,
                }
            ]
        }
    )

    id: int
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    # Đang là manager của chính bộ phận này.
    is_manager: bool


class ManagerAssign(BaseModel):
    # Field lạ trả 422 như DepartmentCreate, DepartmentUpdate.
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"user_id": seed_id(EXAMPLE_MANAGER)}]}
    )

    user_id: Id


class DepartmentManagerOut(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [_MANAGER_EXAMPLE]})

    id: int
    email: str
    full_name: str
    assigned_at: datetime


class DepartmentDetailOut(DepartmentOut):
    """Bộ phận kèm manager (sắp theo họ tên) và số thành viên, cho manager xem bộ phận mình."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{**_DEPARTMENT_EXAMPLE, "managers": [_MANAGER_EXAMPLE], "member_count": 3}]
        }
    )

    managers: list[DepartmentManagerOut]
    member_count: int


class MemberCandidateListParams(PageParams):
    keyword: Annotated[
        Keyword | None, Field(description="Tìm theo họ tên (không dấu) hoặc email")
    ] = None


MemberCandidateListQuery = Annotated[MemberCandidateListParams, Query()]


class MemberCandidateOut(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": EXAMPLE_NEW_USER_ID,
                    "email": EXAMPLE_NEW_USER.email,
                    "full_name": EXAMPLE_NEW_USER.full_name,
                }
            ]
        },
    )

    id: int
    email: str
    full_name: str


class MembersAdd(BaseModel):
    # Field lạ trả 422 như các body khác của module.
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"user_ids": [EXAMPLE_NEW_USER_ID]}]}
    )

    user_ids: Annotated[
        list[Id],
        Field(
            min_length=DEPARTMENT_MEMBERS_ADD_MIN,
            max_length=DEPARTMENT_MEMBERS_ADD_MAX,
            description="Id nhân viên, lấy từ GET /manager/candidates. Id trùng được gộp.",
        ),
        AfterValidator(drop_duplicates),
    ]
