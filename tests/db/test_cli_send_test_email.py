from typing import Any

import pytest
from kombu.exceptions import OperationalError
from redis.asyncio import Redis

from app.modules.notifications.models import EmailTemplate
from app.modules.notifications.tasks import send_email
from tests.helpers import invoke, queued_tasks


async def test_send_test_email_enqueues_task_on_redis(redis: Redis) -> None:
    result = await invoke("send-test-email", "An@Example.com")

    assert result.exit_code == 0, result.output
    assert "an@example.com" in result.output.lower()
    [task] = await queued_tasks(redis)
    assert task.name == send_email.name
    to_email, template, context = task.args
    assert to_email.lower() == "an@example.com"
    assert template == EmailTemplate.TEST
    assert set(context) == {"requested_at"}
    assert task.kwargs == {}


async def test_send_test_email_rejects_invalid_address(redis: Redis) -> None:
    result = await invoke("send-test-email", "khong-phai-email")

    assert result.exit_code == 1
    assert "to:" in result.output
    assert await queued_tasks(redis) == []


async def test_send_test_email_reports_broker_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def broker_down(*_: Any, **__: Any) -> None:
        raise OperationalError("Error 111 connecting to redis:6379. Connection refused.")

    monkeypatch.setattr(send_email, "delay", broker_down)

    result = await invoke("send-test-email", "an@example.com")

    assert result.exit_code == 1
    assert "Không đẩy được task vào Redis" in result.output
