from datetime import date

import pytest
from redis.asyncio import Redis

from app.cli import email
from app.core.clock import local_today
from app.core.constants import MONTH_FORMAT
from app.modules.reports.tasks import send_monthly_summaries
from tests.helpers import invoke, queued_tasks


async def test_send_monthly_summary_enqueues_task_for_given_month(redis: Redis) -> None:
    result = await invoke("send-monthly-summary", "--month", "2026-10")

    assert result.exit_code == 0, result.output
    assert "2026-10" in result.output
    [task] = await queued_tasks(redis)
    assert (task.name, task.args, task.kwargs) == (send_monthly_summaries.name, ["2026-10"], {})


async def test_send_monthly_summary_defaults_to_previous_month(
    redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(email, "local_today", lambda: date(2026, 1, 15))

    result = await invoke("send-monthly-summary")

    assert result.exit_code == 0, result.output
    [task] = await queued_tasks(redis)
    assert task.args == ["2025-12"]


@pytest.mark.parametrize(
    ("month", "message"),
    [
        ("10/2026", "không đúng dạng YYYY-MM"),
        # Gửi trước khi hết tháng sẽ giữ dedup_key, lần chạy đúng lịch không gửi nữa.
        (local_today().strftime(MONTH_FORMAT), "chưa kết thúc"),
    ],
    ids=["wrong-format", "current-month"],
)
async def test_send_monthly_summary_rejects_invalid_month(
    redis: Redis, month: str, message: str
) -> None:
    result = await invoke("send-monthly-summary", "--month", month)

    assert result.exit_code == 1
    assert message in result.output
    assert await queued_tasks(redis) == []
