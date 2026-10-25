from typing import Literal

from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 (loại token theo OAuth2, không phải mật khẩu)
    expires_in: int = Field(description="Số giây đến khi access token hết hạn")
