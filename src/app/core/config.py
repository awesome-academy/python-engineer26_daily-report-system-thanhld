"""Cấu hình ứng dụng, đọc từ biến môi trường và file .env."""

from functools import lru_cache
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, NameEmail, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_SECRET_MIN_LENGTH,
    REFRESH_TOKEN_EXPIRE_DAYS,
    Environment,
)

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
    # Test xóa sạch DB Redis này trước mỗi test. Chạy test song song ở nhiều worktree thì mỗi
    # nơi đặt một DB khác nhau, như TEST_DATABASE_URL.
    test_redis_url: str = "redis://localhost:6380/15"

    jwt_secret_key: str = Field(default=DEV_JWT_SECRET_KEY, min_length=JWT_SECRET_MIN_LENGTH)
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=ACCESS_TOKEN_EXPIRE_MINUTES, ge=1)
    refresh_token_expire_days: int = Field(default=REFRESH_TOKEN_EXPIRE_DAYS, ge=1)

    # SMTP cho Celery worker gửi email. Mặc định trỏ vào Mailpit (make services) khi chạy trên
    # máy host; trong Docker, docker-compose.yml đặt SMTP_HOST=mailpit, SMTP_PORT=1025.
    smtp_host: str = "localhost"
    smtp_port: int = Field(default=1026, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    # Mailpit không có TLS. SMTP thật (Gmail, SES) dùng cổng 587 và bật STARTTLS.
    smtp_starttls: bool = False
    mail_from: NameEmail = NameEmail("Daily Report", "no-reply@example.com")

    # Múi giờ nghiệp vụ: dùng để tính "hôm nay" cho ngày báo cáo và thống kê tháng.
    timezone: str = "Asia/Ho_Chi_Minh"
    cors_origins: list[str] = Field(default_factory=list)

    @property
    def json_logs(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        # Kiểm tra lúc khởi động: sai tên múi giờ thì app không chạy, thay vì mọi request cần
        # "hôm nay" (tạo báo cáo) trả 500.
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            msg = f"Múi giờ không hợp lệ: {value!r}, ví dụ đúng: Asia/Ho_Chi_Minh."
            raise ValueError(msg) from exc
        return value

    @field_validator("smtp_username", "smtp_password", mode="before")
    @classmethod
    def _blank_smtp_credential_to_none(cls, value: object) -> object:
        # `SMTP_USERNAME=` để trống (như .env.example) đọc ra "": coi là không đặt, nếu không
        # worker đăng nhập bằng chuỗi rỗng và Mailpit (không có đăng nhập) từ chối mọi email.
        return value or None

    @model_validator(mode="after")
    def _require_smtp_credentials_in_pairs(self) -> Self:
        # Chỉ đặt một trong hai thì worker bỏ qua bước đăng nhập, mọi email đều lỗi lúc gửi.
        if (self.smtp_username is None) != (self.smtp_password is None):
            msg = "SMTP_USERNAME và SMTP_PASSWORD phải cùng được đặt hoặc cùng bỏ trống."
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _require_secret_key_in_production(self) -> Self:
        if self.environment is Environment.PRODUCTION and self.jwt_secret_key == DEV_JWT_SECRET_KEY:
            msg = "JWT_SECRET_KEY phải được đặt riêng khi chạy production."
            raise ValueError(msg)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
