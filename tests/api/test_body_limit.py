"""Giới hạn dung lượng body của mọi request (BodySizeLimitMiddleware, OWASP API4).

FastAPI đọc hết body (JSON vào RAM, file multipart ra file tạm) trước khi chạy dependency xác thực
và trước khi endpoint upload kiểm tra dung lượng file, nên body quá lớn phải bị chặn trước đó.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient

from app.core.constants import BYTES_PER_MB, REQUEST_BODY_MAX_BYTES, REQUEST_BODY_MAX_MB
from tests.helpers import REFRESH_URL

AVATAR_URL = "/api/v1/me/avatar"
TOO_LARGE_ERROR = {
    "error": {
        "code": "REQUEST_TOO_LARGE",
        "message": f"Dữ liệu gửi lên vượt quá dung lượng cho phép ({REQUEST_BODY_MAX_MB} MB).",
        "details": {"max_bytes": REQUEST_BODY_MAX_BYTES},
    }
}


async def chunked(size: int, chunk_size: int = BYTES_PER_MB) -> AsyncIterator[bytes]:
    # Nội dung là generator: httpx gửi từng đoạn, không có header Content-Length.
    for start in range(0, size, chunk_size):
        yield b"x" * min(chunk_size, size - start)


async def test_body_over_limit_is_rejected_before_authentication(client: AsyncClient) -> None:
    # Chưa đăng nhập vẫn bị chặn ở dung lượng: không có middleware thì app đọc hết file ra đĩa rồi
    # mới trả 401.
    response = await client.put(
        AVATAR_URL, files={"file": ("anh.png", b"x" * REQUEST_BODY_MAX_BYTES)}
    )

    assert response.status_code == 413
    assert response.json() == TOO_LARGE_ERROR
    # Lỗi đi qua các middleware khác như mọi response: có request-id để tra log.
    assert "X-Request-ID" in response.headers


async def test_streamed_body_over_limit_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        REFRESH_URL,
        content=chunked(REQUEST_BODY_MAX_BYTES + 1),
        headers={"Content-Type": "application/json"},
    )

    assert "Content-Length" not in response.request.headers
    assert response.status_code == 413
    assert response.json() == TOO_LARGE_ERROR


@pytest.mark.parametrize("streamed", [False, True], ids=["content-length", "streamed"])
async def test_body_at_limit_reaches_endpoint(client: AsyncClient, streamed: bool) -> None:
    size = REQUEST_BODY_MAX_BYTES
    body = chunked(size) if streamed else b"x" * size

    response = await client.post(
        REFRESH_URL, content=body, headers={"Content-Type": "application/json"}
    )

    # Endpoint nhận đủ body và báo JSON sai, không phải lỗi dung lượng.
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
