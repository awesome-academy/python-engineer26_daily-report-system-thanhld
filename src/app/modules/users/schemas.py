from datetime import date, datetime
from typing import Annotated

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
from app.core.validators import Id, Keyword, NoNul, reject_null
from app.modules.users.models import UserRole


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


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    phone: str | None
    date_of_birth: date | None
    role: UserRole
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class AdminUserOut(UserOut):
    department_id: int | None


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

    model_config = ConfigDict(extra="forbid")

    full_name: FullName | None = None
    phone: Phone | None = None
    date_of_birth: PastDate | None = None

    _not_null = field_validator("full_name")(reject_null)


class PasswordChange(BaseModel):
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

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

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
