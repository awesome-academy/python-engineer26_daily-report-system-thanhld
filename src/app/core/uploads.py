"""Đọc và kiểm tra file người dùng tải lên (UploadFile), dùng chung cho các endpoint upload."""

from collections.abc import Iterable
from dataclasses import dataclass

from fastapi import UploadFile, status

from app.core.constants import BYTES_PER_MB, IMAGE_SIGNATURES, ImageType
from app.core.exceptions import AppError, ErrorCode

# Tên field multipart của các endpoint upload, dùng cho `details.field` của lỗi.
UPLOAD_FIELD = "file"


class FileTooLargeError(AppError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = ErrorCode.FILE_TOO_LARGE

    def __init__(self, max_bytes: int) -> None:
        super().__init__(
            f"File vượt quá dung lượng cho phép ({max_bytes / BYTES_PER_MB:g} MB).",
            details={"field": UPLOAD_FIELD, "max_bytes": max_bytes},
        )


class UnsupportedFileTypeError(AppError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = ErrorCode.UNSUPPORTED_FILE_TYPE

    def __init__(self, allowed: Iterable[ImageType]) -> None:
        types = [image_type.value for image_type in allowed]
        super().__init__(
            f"Loại file không được hỗ trợ, chỉ nhận {', '.join(types)}.",
            details={"field": UPLOAD_FIELD, "allowed_types": types},
        )


@dataclass(frozen=True, slots=True)
class UploadedImage:
    data: bytes
    type: ImageType


async def read_upload(file: UploadFile, max_bytes: int) -> bytes:
    """Đọc nội dung file, quá `max_bytes` thì báo lỗi 413.

    Chỉ đọc tối đa `max_bytes + 1` byte: đủ biết file quá giới hạn mà không nạp cả file lớn vào
    bộ nhớ.
    """
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise FileTooLargeError(max_bytes)
    return data


def detect_image_type(data: bytes) -> ImageType | None:
    """Loại ảnh theo các byte đầu của nội dung; không phải ảnh đã biết thì trả None."""
    return next(
        (image_type for image_type, sig in IMAGE_SIGNATURES.items() if data.startswith(sig)), None
    )


async def read_image(
    file: UploadFile, max_bytes: int, allowed: tuple[ImageType, ...]
) -> UploadedImage:
    """Đọc file ảnh: quá dung lượng trả 413, không phải loại ảnh trong `allowed` trả 415.

    Không tin Content-Type, tên file client gửi (đổi đuôi .exe thành .png là qua); chỉ xét nội dung.
    """
    data = await read_upload(file, max_bytes)
    image_type = detect_image_type(data)
    if image_type not in allowed:
        raise UnsupportedFileTypeError(allowed)
    return UploadedImage(data=data, type=image_type)
