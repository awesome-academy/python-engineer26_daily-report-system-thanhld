from io import BytesIO

import pytest
from fastapi import UploadFile

from app.core.constants import AVATAR_IMAGE_TYPES, BYTES_PER_MB, IMAGE_SIGNATURES, ImageType
from app.core.uploads import (
    FileTooLargeError,
    UnsupportedFileTypeError,
    detect_image_type,
    read_image,
)

PNG = IMAGE_SIGNATURES[ImageType.PNG] + b"noi-dung"
MAX_BYTES = 64


def upload(data: bytes, filename: str = "anh.png") -> UploadFile:
    return UploadFile(BytesIO(data), filename=filename)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        pytest.param(b"\xff\xd8\xff\xe0JFIF", ImageType.JPEG, id="jpeg"),
        pytest.param(PNG, ImageType.PNG, id="png"),
        pytest.param(b"GIF89a", None, id="gif"),
        pytest.param(b"\x89PNG", None, id="png-truncated-signature"),
        pytest.param(b"", None, id="empty"),
    ],
)
def test_detect_image_type_reads_magic_bytes(data: bytes, expected: ImageType | None) -> None:
    assert detect_image_type(data) is expected


async def test_read_image_accepts_file_at_size_limit() -> None:
    data = PNG.ljust(MAX_BYTES, b"\0")

    image = await read_image(upload(data), MAX_BYTES, AVATAR_IMAGE_TYPES)

    assert (image.data, image.type) == (data, ImageType.PNG)


async def test_read_image_rejects_file_over_size_limit() -> None:
    data = PNG.ljust(MAX_BYTES + 1, b"\0")

    with pytest.raises(FileTooLargeError) as exc_info:
        await read_image(upload(data), MAX_BYTES, AVATAR_IMAGE_TYPES)

    assert exc_info.value.details == {"field": "file", "max_bytes": MAX_BYTES}


async def test_read_image_rejects_type_not_allowed() -> None:
    # Chỉ nhận PNG: JPEG đúng định dạng vẫn bị từ chối, message liệt kê đúng loại được nhận.
    with pytest.raises(UnsupportedFileTypeError, match=r"chỉ nhận image/png\.") as exc_info:
        await read_image(upload(b"\xff\xd8\xff\xe0"), MAX_BYTES, (ImageType.PNG,))

    assert exc_info.value.details == {"field": "file", "allowed_types": ["image/png"]}


def test_file_too_large_message_shows_limit_in_megabytes() -> None:
    assert "(2 MB)" in FileTooLargeError(2 * BYTES_PER_MB).message
