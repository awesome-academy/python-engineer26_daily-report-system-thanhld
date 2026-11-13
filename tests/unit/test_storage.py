from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from botocore.stub import Stubber
from pydantic import HttpUrl

from app.core.config import Settings, get_settings
from app.core.constants import (
    S3_CONNECT_TIMEOUT_SECONDS,
    S3_MAX_ATTEMPTS,
    S3_PRESIGNED_URL_EXPIRE_SECONDS,
    S3_READ_TIMEOUT_SECONDS,
    StorageBackend,
)
from app.core.storage import (
    LocalFileStorage,
    S3FileStorage,
    StorageError,
    build_storage,
    create_s3_client,
    get_storage,
)

BASE_URL = "http://localhost:8001/media"
KEY = "avatars/7/abc.png"
DATA = b"\x89PNG\r\n\x1a\nnoi-dung"


def s3_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "storage_backend": StorageBackend.S3,
        "s3_bucket": "daily-report",
        "s3_region": "ap-southeast-1",
        "s3_access_key_id": "test-key",
        "s3_secret_access_key": "test-secret",
    } | overrides
    return Settings.model_validate(values)


@pytest.fixture
def local(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path, BASE_URL)


@pytest.fixture
def s3() -> S3FileStorage:
    return S3FileStorage(create_s3_client(s3_settings()), "daily-report")


async def test_local_storage_saves_file_in_nested_directory(
    local: LocalFileStorage, tmp_path: Path
) -> None:
    await local.save(KEY, DATA, "image/png")

    assert (tmp_path / KEY).read_bytes() == DATA


async def test_local_storage_deletes_file_and_ignores_missing_key(
    local: LocalFileStorage, tmp_path: Path
) -> None:
    await local.save(KEY, DATA, "image/png")

    await local.delete(KEY)
    await local.delete(KEY)

    assert not (tmp_path / KEY).exists()


def test_local_storage_url_joins_base_url_and_key(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path, f"{BASE_URL}/")

    assert storage.url(KEY) == f"{BASE_URL}/{KEY}"


@pytest.mark.parametrize("key", ["../ngoai.png", "avatars/../../ngoai.png", "/etc/passwd", ""])
async def test_local_storage_rejects_key_outside_root(local: LocalFileStorage, key: str) -> None:
    with pytest.raises(ValueError, match="Key không hợp lệ"):
        await local.save(key, DATA, "image/png")


async def test_local_storage_wraps_os_errors(tmp_path: Path) -> None:
    # Thư mục lưu trữ là một file: không tạo được thư mục con, không xóa được.
    root = tmp_path / "media"
    root.write_bytes(b"")
    storage = LocalFileStorage(root, BASE_URL)

    with pytest.raises(StorageError):
        await storage.save(KEY, DATA, "image/png")
    with pytest.raises(StorageError):
        await storage.delete(KEY)


async def test_s3_storage_puts_object_with_content_type(s3: S3FileStorage) -> None:
    with Stubber(s3.client) as stub:
        stub.add_response(
            "put_object",
            {},
            {"Bucket": "daily-report", "Key": KEY, "Body": DATA, "ContentType": "image/png"},
        )

        await s3.save(KEY, DATA, "image/png")

        stub.assert_no_pending_responses()


async def test_s3_storage_deletes_object(s3: S3FileStorage) -> None:
    with Stubber(s3.client) as stub:
        stub.add_response("delete_object", {}, {"Bucket": "daily-report", "Key": KEY})

        await s3.delete(KEY)

        stub.assert_no_pending_responses()


async def save_key(storage: S3FileStorage) -> None:
    await storage.save(KEY, DATA, "image/png")


async def delete_key(storage: S3FileStorage) -> None:
    await storage.delete(KEY)


@pytest.mark.parametrize(
    ("operation", "call"),
    [("put_object", save_key), ("delete_object", delete_key)],
    ids=["save", "delete"],
)
async def test_s3_storage_wraps_client_errors(
    s3: S3FileStorage, operation: str, call: Callable[[S3FileStorage], Awaitable[None]]
) -> None:
    with Stubber(s3.client) as stub:
        stub.add_client_error(operation, service_error_code="AccessDenied", http_status_code=403)

        with pytest.raises(StorageError, match="AccessDenied"):
            await call(s3)


def test_s3_storage_url_is_presigned_with_expiry(s3: S3FileStorage) -> None:
    url = urlsplit(s3.url(KEY))

    assert url.path.endswith(f"/{KEY}")
    query = parse_qs(url.query)
    assert query["X-Amz-Expires"] == [str(S3_PRESIGNED_URL_EXPIRE_SECONDS)]
    assert "X-Amz-Signature" in query


def test_s3_client_uses_bounded_timeouts() -> None:
    # Stub của botocore không khai các thuộc tính của Config (đặt động lúc chạy).
    config: Any = create_s3_client(s3_settings()).meta.config

    assert config.connect_timeout == S3_CONNECT_TIMEOUT_SECONDS
    assert config.read_timeout == S3_READ_TIMEOUT_SECONDS
    assert config.retries["total_max_attempts"] == S3_MAX_ATTEMPTS


def test_s3_compatible_endpoint_uses_path_style_url() -> None:
    # MinIO: http://host/bucket/key, không đổi bucket thành subdomain.
    settings = s3_settings(s3_endpoint_url="http://localhost:9000")

    url = build_storage(settings).url(KEY)

    assert url.startswith(f"http://localhost:9000/daily-report/{KEY}?")


def test_build_storage_uses_local_backend_from_settings(tmp_path: Path) -> None:
    settings = Settings(
        storage_backend=StorageBackend.LOCAL,
        local_storage_dir=tmp_path,
        local_storage_base_url=HttpUrl(BASE_URL),
    )

    storage = build_storage(settings)

    assert isinstance(storage, LocalFileStorage)
    assert storage.url(KEY) == f"{BASE_URL}/{KEY}"


def test_build_storage_uses_s3_backend_from_settings() -> None:
    storage = build_storage(s3_settings())

    assert isinstance(storage, S3FileStorage)
    assert storage.bucket == "daily-report"


def test_build_storage_rejects_s3_without_bucket() -> None:
    # Settings dựng không qua validate (model_construct) vẫn không tạo được storage thiếu bucket.
    settings = Settings.model_construct(storage_backend=StorageBackend.S3, s3_bucket=None)

    with pytest.raises(ValueError, match="S3_BUCKET"):
        build_storage(settings)


def test_get_storage_builds_one_storage_from_app_settings() -> None:
    # conftest đặt STORAGE_BACKEND=local, LOCAL_STORAGE_DIR là thư mục tạm.
    storage = get_storage()

    assert storage is get_storage()
    assert isinstance(storage, LocalFileStorage)
    assert storage.root == get_settings().local_storage_dir.resolve()
