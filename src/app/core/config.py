"""Cấu hình ứng dụng, đọc từ biến môi trường và file .env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, HttpUrl, NameEmail, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_SECRET_MIN_LENGTH,
    REFRESH_TOKEN_EXPIRE_DAYS,
    Environment,
    StorageBackend,
)

# Chỉ dùng khi dev và test. Production bắt buộc đặt JWT_SECRET_KEY riêng.
DEV_JWT_SECRET_KEY = "dev-only-secret-key-change-me-in-production"  # noqa: S105
# Validator của Settings và build_storage (core/storage.py) cùng báo lỗi này.
S3_BUCKET_REQUIRED = "STORAGE_BACKEND=s3 cần đặt S3_BUCKET."


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

    # Địa chỉ frontend, dùng để ghép link trong email (đặt mật khẩu lần đầu).
    frontend_url: HttpUrl = HttpUrl("http://localhost:3000")

    # Lưu trữ file (ảnh đại diện). Đổi backend chỉ cần đổi STORAGE_BACKEND và các biến của backend.
    storage_backend: StorageBackend = StorageBackend.LOCAL
    # Backend local: thư mục lưu file (tương đối thì tính từ thư mục chạy app) và URL công khai
    # tương ứng; API phục vụ thư mục này tại LOCAL_STORAGE_URL_PATH (/media).
    local_storage_dir: Path = Path("media")
    local_storage_base_url: HttpUrl = HttpUrl("http://localhost:8001/media")
    # Backend S3 (AWS S3 hoặc dịch vụ tương thích như MinIO: đặt S3_ENDPOINT_URL). Không đặt khóa
    # truy cập thì boto3 tự tìm theo chuỗi mặc định (biến AWS_*, IAM role).
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: HttpUrl | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None

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

    @field_validator(
        "s3_bucket",
        "s3_region",
        "s3_endpoint_url",
        "s3_access_key_id",
        "s3_secret_access_key",
        mode="before",
    )
    @classmethod
    def _blank_s3_setting_to_none(cls, value: object) -> object:
        # Biến để trống như .env.example: coi là không đặt, để boto3 dùng giá trị mặc định
        # (endpoint của AWS, chuỗi tìm khóa) thay vì chuỗi rỗng.
        return value or None

    @model_validator(mode="after")
    def _require_s3_settings(self) -> Self:
        # Kiểm tra lúc khởi động: thiếu bucket thì app không chạy, thay vì mọi lần upload lỗi 500.
        if self.storage_backend is StorageBackend.S3 and self.s3_bucket is None:
            raise ValueError(S3_BUCKET_REQUIRED)
        if (self.s3_access_key_id is None) != (self.s3_secret_access_key is None):
            msg = "S3_ACCESS_KEY_ID và S3_SECRET_ACCESS_KEY phải cùng được đặt hoặc cùng bỏ trống."
            raise ValueError(msg)
        return self

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
