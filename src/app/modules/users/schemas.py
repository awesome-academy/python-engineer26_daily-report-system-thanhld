from datetime import date, datetime
from typing import Annotated, Any, Self

from fastapi import Query
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    PastDate,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

from app.core import messages
from app.core.constants import (
    EMAIL_MAX_LENGTH,
    FULL_NAME_MAX_LENGTH,
    FULL_NAME_MIN_LENGTH,
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    PHONE_MAX_LENGTH,
    PHONE_PATTERN,
)
from app.core.pagination import PageParams
from app.core.storage import FileStorage
from app.core.validators import Id, Keyword, NoNul, reject_null
from app.modules.users.models import User, UserRole
from app.seed_data import (
    DEPARTMENTS,
    EXAMPLE_DEPARTMENT,
    EXAMPLE_EMPLOYEE,
    EXAMPLE_NEW_USER,
    EXAMPLE_NEW_USER_ID,
    EXAMPLE_PASSWORD,
    seed_id,
)


def _check_password_strength(password: str) -> str:
    rules = {
        "chữ thường": any(char.islower() for char in password),
        "chữ hoa": any(char.isupper() for char in password),
        "chữ số": any(char.isdigit() for char in password),
        "ký tự đặc biệt": any(not char.isalnum() and not char.isspace() for char in password),
    }
    missing = [name for name, ok in rules.items() if not ok]
    if missing:
        raise ValueError(messages.PASSWORD_TOO_WEAK.format(missing=", ".join(missing)))
    return password


Email = Annotated[EmailStr, Field(max_length=EMAIL_MAX_LENGTH)]
# Họ tên bỏ khoảng trắng đầu cuối, nên chuỗi chỉ có dấu cách bị từ chối. Mật khẩu giữ nguyên.
FullName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=FULL_NAME_MIN_LENGTH, max_length=FULL_NAME_MAX_LENGTH
    ),
    NoNul,
]
Phone = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=PHONE_MAX_LENGTH, pattern=PHONE_PATTERN),
]
# Mật khẩu người dùng tự chọn (tạo admin, seed, đổi mật khẩu). Không dùng cho mật khẩu nhập để
# kiểm tra (đăng nhập, mật khẩu hiện tại), để tài khoản đang có mật khẩu yếu vẫn đổi được.
Password = Annotated[
    str,
    Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH),
    AfterValidator(_check_password_strength),
]


# Ví dụ trên Swagger: nhân viên của dữ liệu seed (app.seed_data), để thử ngay sau khi seed.
_USER_EXAMPLE: dict[str, Any] = {
    "id": seed_id(EXAMPLE_EMPLOYEE),
    "email": EXAMPLE_EMPLOYEE.email,
    "full_name": EXAMPLE_EMPLOYEE.full_name,
    "phone": "0912345678",
    "date_of_birth": "1998-05-20",
    "role": EXAMPLE_EMPLOYEE.role,
    "is_active": True,
    "last_login_at": "2026-11-09T01:30:00Z",
    "created_at": "2026-10-26T02:00:00Z",
}
# Tài khoản admin vừa tạo (A1) hoặc import (A4): chưa đặt mật khẩu nên chưa đăng nhập lần nào.
_NEW_USER_EXAMPLE: dict[str, Any] = {
    "id": EXAMPLE_NEW_USER_ID,
    "email": EXAMPLE_NEW_USER.email,
    "full_name": EXAMPLE_NEW_USER.full_name,
    "phone": "0987654321",
    "date_of_birth": "2000-03-15",
    "role": EXAMPLE_NEW_USER.role,
    "is_active": True,
    "last_login_at": None,
    "created_at": "2026-11-09T03:00:00Z",
    "department_id": seed_id(EXAMPLE_DEPARTMENT),
}
_EMPLOYEE_EXAMPLE: dict[str, Any] = {**_USER_EXAMPLE, "department_id": seed_id(EXAMPLE_DEPARTMENT)}


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_extra={"examples": [_USER_EXAMPLE]})

    id: int
    email: str
    full_name: str
    phone: str | None
    date_of_birth: date | None
    role: UserRole
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class ProfileOut(UserOut):
    """Hồ sơ của chính mình (`/me`), kèm URL ảnh đại diện."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    **_USER_EXAMPLE,
                    "avatar_url": "http://localhost:8001/media/avatars/5/9f1c2b7e4d.png",
                }
            ]
        }
    )

    avatar_url: str | None = Field(
        description="Null khi chưa có ảnh. Backend S3 trả URL ký sẵn có hạn: lấy lại qua GET /me"
    )

    @classmethod
    def from_user(cls, user: User, storage: FileStorage) -> Self:
        # DB chỉ lưu key; URL phụ thuộc backend lưu trữ (local hay S3) nên tính lúc trả response.
        avatar_url = storage.url(user.avatar_key) if user.avatar_key else None
        return cls(**UserOut.model_validate(user).model_dump(), avatar_url=avatar_url)


class AdminUserOut(UserOut):
    model_config = ConfigDict(json_schema_extra={"examples": [_EMPLOYEE_EXAMPLE]})

    department_id: int | None


class UserImportResult(BaseModel):
    """Kết quả import: mọi dòng của file đã thành tài khoản, theo thứ tự dòng."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"created_count": 1, "users": [_NEW_USER_EXAMPLE]}]}
    )

    created_count: int
    users: list[AdminUserOut]


class EmployeeOut(UserOut):
    model_config = ConfigDict(json_schema_extra={"examples": [_EMPLOYEE_EXAMPLE]})

    # Nhân viên luôn thuộc một bộ phận manager quản lý; manager quản lý nhiều bộ phận thì cần
    # biết người này ở bộ phận nào.
    department_id: int


class UserCreate(BaseModel):
    email: Email
    full_name: FullName
    password: Password
    role: UserRole = UserRole.USER


class UserProfileUpdate(BaseModel):
    """Cập nhật từng phần: field không gửi thì giữ nguyên, `null` thì xóa giá trị.

    Chỉ có các field user tự sửa được. Gửi email, role hay field lạ thì bị từ chối (422) thay vì
    bỏ qua, để client biết thay đổi đó không có hiệu lực.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"phone": "0912345678", "date_of_birth": "1998-05-20"}]},
    )

    full_name: FullName | None = None
    phone: Phone | None = None
    date_of_birth: PastDate | None = None

    _not_null = field_validator("full_name")(reject_null)


class PasswordChange(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"current_password": EXAMPLE_PASSWORD, "new_password": "Matkhau@456"}]
        }
    )

    current_password: Annotated[str, Field(max_length=PASSWORD_MAX_LENGTH)]
    new_password: Password

    @field_validator("new_password")
    @classmethod
    def _differs_from_current(cls, value: str, info: ValidationInfo) -> str:
        if value == info.data.get("current_password"):
            raise ValueError(messages.NEW_PASSWORD_SAME_AS_CURRENT)
        return value


class AdminUserCreate(BaseModel):
    """Admin tạo tài khoản. Không có mật khẩu: user tự đặt qua link gửi email (Q8, S2)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    key: _NEW_USER_EXAMPLE[key]
                    for key in (
                        "email",
                        "full_name",
                        "phone",
                        "date_of_birth",
                        "role",
                        "department_id",
                    )
                }
            ]
        },
    )

    email: Email
    full_name: FullName
    phone: Phone | None = None
    date_of_birth: PastDate | None = None
    role: UserRole = UserRole.USER
    department_id: Id | None = None


class AdminUserUpdate(BaseModel):
    """Cập nhật từng phần: field không gửi thì giữ nguyên.

    `null` xóa `phone`, `date_of_birth`, `department_id` (gỡ khỏi bộ phận); các field còn lại
    bắt buộc nên không nhận `null`. `is_active = false` là khóa tài khoản.
    """

    model_config = ConfigDict(
        extra="forbid",
        # Chuyển nhân viên sang bộ phận seed thứ hai (QA).
        json_schema_extra={
            "examples": [{"phone": "0987654321", "department_id": seed_id(DEPARTMENTS[1])}]
        },
    )

    email: Email | None = None
    full_name: FullName | None = None
    phone: Phone | None = None
    date_of_birth: PastDate | None = None
    role: UserRole | None = None
    department_id: Id | None = None
    is_active: bool | None = None

    _not_null = field_validator("email", "full_name", "role", "is_active")(reject_null)


class UserListParams(PageParams):
    keyword: Annotated[
        Keyword | None, Field(description="Tìm theo họ tên (không dấu) hoặc email")
    ] = None
    role: UserRole | None = None
    department_id: Id | None = None


UserListQuery = Annotated[UserListParams, Query()]


class EmployeeListParams(PageParams):
    keyword: Annotated[
        Keyword | None, Field(description="Tìm theo họ tên (không dấu) hoặc email")
    ] = None
    department_id: Annotated[
        Id | None, Field(description="Chỉ bộ phận này; phải là bộ phận mình quản lý")
    ] = None
