from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_MAX_LENGTH,
    ONE_TIME_TOKEN_MAX_LENGTH,
    ONE_TIME_TOKEN_PATTERN,
)
from app.modules.users.schemas import Password
from app.seed_data import EXAMPLE_PASSWORD

# Ví dụ trên Swagger. Token thật dài hơn: JWT có header, claim (sub, jti, exp…) và chữ ký.
_ACCESS_JWT_EXAMPLE = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI1IiwidHlwZSI6ImFjY2VzcyJ9.c2lnbg"
)
_REFRESH_JWT_EXAMPLE = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI1IiwidHlwZSI6InJlZnJlc2gifQ.c2lnbg"
)


class TokenResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "access_token": _ACCESS_JWT_EXAMPLE,
                    "refresh_token": _REFRESH_JWT_EXAMPLE,
                    "token_type": "bearer",
                    "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                }
            ]
        }
    )

    access_token: str
    refresh_token: str = Field(
        description="Gửi lên /auth/refresh để lấy cặp token mới khi access token hết hạn"
    )
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 (loại token theo OAuth2, không phải mật khẩu)
    expires_in: int = Field(description="Số giây đến khi access token hết hạn")


class RefreshTokenRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"refresh_token": _REFRESH_JWT_EXAMPLE}]}
    )

    refresh_token: str = Field(max_length=JWT_MAX_LENGTH)


class PasswordSetup(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"token": "dan-token-tu-link-trong-email", "password": EXAMPLE_PASSWORD}]
        },
    )

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
