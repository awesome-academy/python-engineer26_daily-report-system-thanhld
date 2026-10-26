"""Cấu hình ứng dụng, đọc từ biến môi trường và file .env."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import ACCESS_TOKEN_EXPIRE_MINUTES, JWT_SECRET_MIN_LENGTH, Environment

# Chỉ dùng khi dev và test. Production bắt buộc đặt JWT_SECRET_KEY riêng.
DEV_JWT_SECRET_KEY = "dev-only-secret-key-change-me-in-production"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Daily Report API"
    environment: Environment = Environment.LOCAL
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # Tiền tố chung của các router nghiệp vụ. /health không dùng tiền tố này.
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://daily_report:daily_report@localhost:5433/daily_report"
    test_database_url: str = (
        "postgresql+asyncpg://daily_report:daily_report@localhost:5433/daily_report_test"
    )
    redis_url: str = "redis://localhost:6380/0"

    jwt_secret_key: str = Field(default=DEV_JWT_SECRET_KEY, min_length=JWT_SECRET_MIN_LENGTH)
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=ACCESS_TOKEN_EXPIRE_MINUTES, ge=1)

    # Múi giờ nghiệp vụ: dùng để tính "hôm nay" cho ngày báo cáo và thống kê tháng.
    timezone: str = "Asia/Ho_Chi_Minh"
    cors_origins: list[str] = Field(default_factory=list)

    @property
    def json_logs(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @model_validator(mode="after")
    def _require_secret_key_in_production(self) -> Self:
        if self.environment is Environment.PRODUCTION and self.jwt_secret_key == DEV_JWT_SECRET_KEY:
            msg = "JWT_SECRET_KEY phải được đặt riêng khi chạy production."
            raise ValueError(msg)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
