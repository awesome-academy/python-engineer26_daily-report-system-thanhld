from datetime import date

import pytest
from redis.asyncio import Redis

from app.cli import email
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
    ("today", "month", "expected"),
    [
        # Ngày 1 vẫn còn ở tháng mới: tháng trước đã kết thúc.
        (date(2026, 11, 1), "2026-10", "2026-10"),
        (date(2026, 1, 1), None, "2025-12"),
    ],
)
async def test_send_monthly_summary_accepts_finished_month_from_first_day(
    redis: Redis,
    monkeypatch: pytest.MonkeyPatch,
    today: date,
    month: str | None,
    expected: str,
) -> None:
    monkeypatch.setattr(email, "local_today", lambda: today)

    result = await invoke("send-monthly-summary", *(["--month", month] if month else []))

    assert result.exit_code == 0, result.output
    [task] = await queued_tasks(redis)
    assert task.args == [expected]


@pytest.mark.parametrize(
    ("month", "message"),
    [
        ("10/2026", "không đúng dạng YYYY-MM"),
        # Năm dưới 1000: strftime trên Linux in "1-01", worker sẽ từ chối nhãn đã đẩy.
        ("0001-01", "không đúng dạng YYYY-MM"),
        # Gửi trước khi hết tháng sẽ giữ dedup_key, lần chạy đúng lịch không gửi nữa.
        ("2026-11", "chưa kết thúc"),
    ],
    ids=["wrong-format", "year-below-1000", "current-month"],
)
async def test_send_monthly_summary_rejects_invalid_month(
    redis: Redis, monkeypatch: pytest.MonkeyPatch, month: str, message: str
) -> None:
    monkeypatch.setattr(email, "local_today", lambda: date(2026, 11, 1))

    result = await invoke("send-monthly-summary", "--month", month)

    assert result.exit_code == 1
    assert message in result.output
    assert await queued_tasks(redis) == []
