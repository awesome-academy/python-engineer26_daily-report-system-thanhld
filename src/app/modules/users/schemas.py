from datetime import date, datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    PastDate,
    StringConstraints,
    field_validator,
)

from app.core.constants import (
    EMAIL_MAX_LENGTH,
    FULL_NAME_MAX_LENGTH,
    FULL_NAME_MIN_LENGTH,
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    PHONE_MAX_LENGTH,
    PHONE_PATTERN,
)
from app.modules.users.models import UserRole

Email = Annotated[EmailStr, Field(max_length=EMAIL_MAX_LENGTH)]
# Họ tên bỏ khoảng trắng đầu cuối, nên chuỗi chỉ có dấu cách bị từ chối. Mật khẩu giữ nguyên.
FullName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=FULL_NAME_MIN_LENGTH, max_length=FULL_NAME_MAX_LENGTH
    ),
]
Phone = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=PHONE_MAX_LENGTH, pattern=PHONE_PATTERN),
]
Password = Annotated[str, Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)]


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

    @field_validator("full_name")
    @classmethod
    def _full_name_not_null(cls, value: str | None) -> str | None:
        # Chỉ chạy khi client gửi field này: họ tên bắt buộc nên không được xóa bằng null.
        if value is None:
            msg = "Họ tên không được để trống."
            raise ValueError(msg)
        return value
