"""Lưu trữ file người dùng tải lên: local hoặc S3, chọn bằng cấu hình STORAGE_BACKEND.

Code nghiệp vụ chỉ dùng interface `FileStorage` (nhận qua dependency `Storage`), không biết file
nằm ở đâu, nên đổi backend không phải sửa code.
"""

import asyncio
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import S3_BUCKET_REQUIRED, Settings, get_settings
from app.core.constants import (
    S3_CONNECT_TIMEOUT_SECONDS,
    S3_MAX_ATTEMPTS,
    S3_PRESIGNED_URL_EXPIRE_SECONDS,
    S3_READ_TIMEOUT_SECONDS,
    StorageBackend,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class StorageError(Exception):
    """Backend lưu trữ lỗi (đĩa, mạng, quyền). Nơi gọi bắt lỗi này, không cần biết backend nào."""


class FileStorage(ABC):
    """Kho lưu file theo key dạng đường dẫn tương đối (`avatars/7/ab12.png`)."""

    @abstractmethod
    async def save(self, key: str, data: bytes, content_type: str) -> None:
        """Ghi file, key đã có thì ghi đè."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Xóa file; key không tồn tại thì bỏ qua."""

    @abstractmethod
    def url(self, key: str) -> str:
        """URL client dùng để tải file."""


class LocalFileStorage(FileStorage):
    """Lưu vào thư mục trên máy chạy API; API phục vụ thư mục này tại LOCAL_STORAGE_URL_PATH.

    Hợp khi dev và khi chạy một instance. Nhiều instance thì dùng S3, hoặc thư mục dùng chung.
    """

    def __init__(self, root: Path, base_url: str) -> None:
        self.root = root.resolve()
        self.base_url = base_url.rstrip("/")

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        # Key do app sinh, vẫn chặn "../" hay đường dẫn tuyệt đối ghi ra ngoài thư mục lưu trữ.
        if not path.is_relative_to(self.root) or path == self.root:
            msg = f"Key không hợp lệ: {key!r}"
            raise ValueError(msg)
        return path

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        # Không lưu content_type: StaticFiles suy loại file từ đuôi trong key.
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        try:
            await asyncio.to_thread(write)
        except OSError as exc:
            raise StorageError(str(exc)) from exc

    async def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError as exc:
            raise StorageError(str(exc)) from exc

    def url(self, key: str) -> str:
        return f"{self.base_url}/{self._path(key).relative_to(self.root).as_posix()}"


class S3FileStorage(FileStorage):
    """Lưu lên bucket S3 private; client tải file bằng URL ký sẵn có hạn.

    boto3 là thư viện đồng bộ: lệnh gọi mạng chạy trong thread riêng để không chặn event loop.
    Tạo URL ký sẵn chỉ tính chữ ký tại chỗ, không gọi mạng.
    """

    def __init__(self, client: "S3Client", bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        try:
            await asyncio.to_thread(
                self.client.put_object,
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(str(exc)) from exc

    async def delete(self, key: str) -> None:
        # S3 xóa key không tồn tại vẫn trả thành công.
        try:
            await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(str(exc)) from exc

    def url(self, key: str) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=S3_PRESIGNED_URL_EXPIRE_SECONDS,
        )


def create_s3_client(settings: Settings) -> "S3Client":
    secret = settings.s3_secret_access_key
    endpoint = settings.s3_endpoint_url
    return boto3.client(
        "s3",
        region_name=settings.s3_region,
        endpoint_url=str(endpoint).rstrip("/") if endpoint else None,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=secret.get_secret_value() if secret else None,
        config=Config(
            connect_timeout=S3_CONNECT_TIMEOUT_SECONDS,
            read_timeout=S3_READ_TIMEOUT_SECONDS,
            retries={"total_max_attempts": S3_MAX_ATTEMPTS, "mode": "standard"},
            signature_version="s3v4",
            # Dịch vụ tương thích S3 (MinIO) thường chỉ hỗ trợ dạng http://host/bucket/key.
            s3={"addressing_style": "path" if endpoint else "auto"},
        ),
    )


def build_storage(settings: Settings) -> FileStorage:
    if settings.storage_backend is StorageBackend.S3:
        # Validator của Settings đã chặn trường hợp này; kiểm tra lại để mypy biết có bucket.
        if settings.s3_bucket is None:
            raise ValueError(S3_BUCKET_REQUIRED)
        return S3FileStorage(create_s3_client(settings), settings.s3_bucket)
    return LocalFileStorage(settings.local_storage_dir, str(settings.local_storage_base_url))


@lru_cache
def get_storage() -> FileStorage:
    """Một kho lưu trữ cho cả app (client boto3 dùng chung được giữa các thread)."""
    return build_storage(get_settings())
