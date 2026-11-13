import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.constants import JWT_SECRET_MIN_LENGTH, Environment, StorageBackend


def test_production_requires_own_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(environment=Environment.PRODUCTION)


def test_production_accepts_custom_jwt_secret() -> None:
    settings = Settings(
        environment=Environment.PRODUCTION, jwt_secret_key="s" * JWT_SECRET_MIN_LENGTH
    )

    assert settings.json_logs


def test_rejects_jwt_secret_shorter_than_hs256_minimum() -> None:
    with pytest.raises(ValidationError, match="jwt_secret_key"):
        Settings(jwt_secret_key="s" * (JWT_SECRET_MIN_LENGTH - 1))


def test_local_uses_readable_logs() -> None:
    assert not Settings(environment=Environment.LOCAL).json_logs


def test_rejects_unknown_environment() -> None:
    with pytest.raises(ValidationError, match="environment"):
        Settings(environment="prod")  # type: ignore[arg-type]


@pytest.mark.parametrize("timezone", ["Asia/Hanoi_City", "", "../etc/passwd"])
def test_rejects_unknown_timezone(timezone: str) -> None:
    # Sai múi giờ phải báo ngay khi khởi động, không để mỗi request tạo báo cáo trả 500.
    with pytest.raises(ValidationError, match="timezone"):
        Settings(timezone=timezone)


@pytest.mark.parametrize(
    "credentials",
    [{"smtp_username": "mailer"}, {"smtp_password": "bi-mat"}],
    ids=["username-only", "password-only"],
)
def test_rejects_smtp_username_without_password(credentials: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="SMTP_USERNAME"):
        Settings(**credentials)  # type: ignore[arg-type]


def test_blank_smtp_credentials_mean_no_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_USERNAME", "")
    monkeypatch.setenv("SMTP_PASSWORD", "")

    settings = Settings()

    assert settings.smtp_username is None
    assert settings.smtp_password is None


def test_s3_backend_requires_bucket() -> None:
    # Thiếu bucket phải báo ngay khi khởi động, không để mọi lần upload ảnh trả 500.
    with pytest.raises(ValidationError, match="S3_BUCKET"):
        Settings(storage_backend=StorageBackend.S3, s3_bucket="")


def test_s3_backend_accepts_bucket_without_keys() -> None:
    # Không đặt khóa: boto3 tự tìm khóa theo chuỗi mặc định (biến AWS_*, IAM role).
    settings = Settings(storage_backend=StorageBackend.S3, s3_bucket="daily-report")

    assert settings.s3_access_key_id is None
    assert settings.s3_secret_access_key is None


@pytest.mark.parametrize(
    "keys",
    [{"s3_access_key_id": "key"}, {"s3_secret_access_key": "secret"}],
    ids=["only-key-id", "only-secret"],
)
def test_s3_access_keys_must_be_set_together(keys: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="S3_ACCESS_KEY_ID"):
        Settings.model_validate({"s3_bucket": "daily-report", **keys})


def test_blank_s3_settings_are_treated_as_unset() -> None:
    # Biến để trống như .env.example: dùng endpoint, region mặc định của boto3, không phải "".
    settings = Settings.model_validate(
        {"s3_endpoint_url": "", "s3_region": "", "s3_access_key_id": "", "s3_secret_access_key": ""}
    )

    assert (settings.s3_endpoint_url, settings.s3_region, settings.s3_access_key_id) == (None,) * 3
    assert settings.s3_secret_access_key is None


@pytest.mark.parametrize(
    "field", ["local_storage_base_url", "s3_endpoint_url"], ids=["local-base-url", "s3-endpoint"]
)
def test_storage_urls_must_be_absolute_http_urls(field: str) -> None:
    # Thiếu scheme thì avatar_url trả cho client hỏng, boto3 báo lỗi ở lần upload đầu tiên:
    # phải báo ngay khi khởi động.
    with pytest.raises(ValidationError, match=field):
        Settings.model_validate({field: "localhost:8001/media"})
