from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import JWT_MAX_LENGTH, ONE_TIME_TOKEN_MAX_LENGTH, ONE_TIME_TOKEN_PATTERN
from app.modules.users.schemas import Password


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str = Field(
        description="Gửi lên /auth/refresh để lấy cặp token mới khi access token hết hạn"
    )
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 (loại token theo OAuth2, không phải mật khẩu)
    expires_in: int = Field(description="Số giây đến khi access token hết hạn")


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(max_length=JWT_MAX_LENGTH)


class PasswordSetup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Chỉ ký tự của base64url: chuỗi lạ (kể cả NUL) bị chặn ở 422 trước khi băm.
    token: Annotated[
        str,
        Field(
            max_length=ONE_TIME_TOKEN_MAX_LENGTH,
            pattern=ONE_TIME_TOKEN_PATTERN,
            description="Giá trị `token` trên link đặt mật khẩu trong email",
        ),
    ]
    password: Password
