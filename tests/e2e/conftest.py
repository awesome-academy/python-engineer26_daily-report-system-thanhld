"""Fixture của test end-to-end: app chạy như thật, chỉ thay SMTP.

Khác `client` ở tests/conftest.py: không thay session DB bằng session rollback. Request commit thật
vào DB test như khi chạy thật, nên task chạy như worker (session đồng bộ, kết nối riêng) đọc được
dữ liệu API vừa ghi. `clean_after` xóa sạch dữ liệu sau mỗi test.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from app.modules.notifications.mailer import SmtpMailer
from app.modules.notifications.rendering import RenderedEmail
from tests.helpers import FakeMailer


@pytest.fixture
async def e2e_client(app: FastAPI, redis: Redis, clean_after: None) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


@pytest.fixture
def mailbox(monkeypatch: pytest.MonkeyPatch) -> FakeMailer:
    """Hộp thư thay SMTP cho mọi task gửi email; phần còn lại của task chạy như thật."""
    fake = FakeMailer()

    def send(_mailer: SmtpMailer, to_email: str, email: RenderedEmail) -> None:
        fake.send(to_email, email)

    monkeypatch.setattr(SmtpMailer, "send", send)
    return fake
