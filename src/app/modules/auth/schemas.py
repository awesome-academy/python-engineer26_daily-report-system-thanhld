from typing import Literal

from pydantic import BaseModel, Field

from app.core.constants import JWT_MAX_LENGTH


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str = Field(
        description="Gửi lên /auth/refresh để lấy cặp token mới khi access token hết hạn"
    )
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 (loại token theo OAuth2, không phải mật khẩu)
    expires_in: int = Field(description="Số giây đến khi access token hết hạn")


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(max_length=JWT_MAX_LENGTH)
