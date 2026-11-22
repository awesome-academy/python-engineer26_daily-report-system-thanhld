"""Giới hạn dung lượng body của mọi request (BodySizeLimitMiddleware, OWASP API4).

FastAPI đọc hết body (JSON vào RAM, file multipart ra file tạm) trước khi chạy dependency xác thực
và trước khi endpoint upload kiểm tra dung lượng file, nên body quá lớn phải bị chặn trước đó.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient

from app.core.body_limit import BodySizeLimitMiddleware
from app.core.config import get_settings
from app.core.constants import BYTES_PER_MB, REQUEST_BODY_MAX_BYTES, REQUEST_BODY_MAX_MB
from tests.helpers import REFRESH_URL

API = get_settings().api_v1_prefix
AVATAR_URL = f"{API}/me/avatar"
TOO_LARGE_ERROR = {
    "error": {
        "code": "REQUEST_TOO_LARGE",
        "message": f"Dữ liệu gửi lên vượt quá dung lượng cho phép ({REQUEST_BODY_MAX_MB} MB).",
        "details": {"max_bytes": REQUEST_BODY_MAX_BYTES},
    }
}


async def chunked(size: int, chunk_size: int = BYTES_PER_MB) -> AsyncIterator[bytes]:
    # Nội dung là generator: httpx gửi từng đoạn, không có header Content-Length. Mỗi đoạn nhường
    # event loop như khi body đến dần qua mạng: app làm việc khác (gửi response) trong lúc chờ.
    for start in range(0, size, chunk_size):
        await asyncio.sleep(0)
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


async def test_declared_body_over_limit_is_rejected_without_reading(client: AsyncClient) -> None:
    body_read = False

    async def body() -> AsyncIterator[bytes]:
        nonlocal body_read
        body_read = True
        yield b"{}"

    response = await client.post(
        REFRESH_URL,
        content=body(),
        headers={"Content-Length": str(REQUEST_BODY_MAX_BYTES + 1)},
    )

    assert response.status_code == 413
    assert response.json() == TOO_LARGE_ERROR
    # Chỉ nhìn Content-Length: chưa nhận byte nào của body.
    assert not body_read


# Server ASGI (uvicorn) chặn Content-Length sai từ trước; app vẫn không được lỗi 500 vì nó.
@pytest.mark.parametrize(
    "content_length", ["²".encode("latin-1"), b"9" * 5000], ids=["not-ascii-digit", "too-long"]
)
async def test_invalid_content_length_falls_back_to_counting(
    client: AsyncClient, content_length: bytes
) -> None:
    response = await client.post(
        REFRESH_URL,
        content=b"x",
        headers={b"Content-Length": content_length, b"Content-Type": b"application/json"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


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


def slow_download_app(client_done: asyncio.Event) -> FastAPI:
    """Endpoint không đọc body, gửi phần đầu file rồi chờ client gửi xong body mới gửi tiếp."""
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=REQUEST_BODY_MAX_BYTES)

    async def content() -> AsyncIterator[bytes]:
        yield b"head "
        await client_done.wait()
        yield b"tail"

    @app.get("/download")
    async def download() -> StreamingResponse:
        return StreamingResponse(content())

    return app


async def test_body_read_after_response_started_does_not_break_it() -> None:
    # Server ASGI dưới spec 2.4 (uvicorn): trong lúc gửi StreamingResponse, Starlette vẫn đọc body
    # để biết client ngắt kết nối. Response đã bắt đầu thì không còn trả 413 được, ném lỗi chỉ làm
    # ngắt response giữa chừng.
    client_done = asyncio.Event()

    async def body() -> AsyncIterator[bytes]:
        async for chunk in chunked(REQUEST_BODY_MAX_BYTES + 1):
            yield chunk
        client_done.set()

    transport = ASGITransport(app=slow_download_app(client_done))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request("GET", "/download", content=body())

    assert response.status_code == 200
    assert response.content == b"head tail"
