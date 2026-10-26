from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.core.constants import (
    EMAIL_MAX_LENGTH,
    FULL_NAME_MAX_LENGTH,
    FULL_NAME_MIN_LENGTH,
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
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
