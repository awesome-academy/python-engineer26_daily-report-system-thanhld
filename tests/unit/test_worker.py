import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from celery import Task
from celery.schedules import crontab
from celery.signals import after_setup_logger, after_setup_task_logger
from celery.utils.dispatch import Signal

from app.core.config import get_settings
from app.core.constants import (
    MONTHLY_SUMMARY_TASK,
    REDIS_TIMEOUT_SECONDS,
    TASK_MAX_RETRIES,
    TASK_RETRY_BACKOFF_SECONDS,
)
from app.modules.auth.tasks import send_account_setup_email
from app.modules.notifications.tasks import send_email
from app.modules.reports.tasks import send_monthly_summaries, send_report_notification
from app.worker import celery_app, retry_countdown


def test_celery_uses_redis_broker_with_json_and_timeouts() -> None:
    conf = celery_app.conf

    assert conf.broker_url == get_settings().redis_url
    assert conf.task_serializer == "json"
    assert conf.accept_content == ["json"]
    assert conf.task_acks_late
    # Redis treo thì đẩy task báo lỗi sau vài giây thay vì treo request.
    assert conf.broker_transport_options == {
        "socket_timeout": REDIS_TIMEOUT_SECONDS,
        "socket_connect_timeout": REDIS_TIMEOUT_SECONDS,
    }


@pytest.mark.parametrize(
    "task",
    [send_email, send_report_notification, send_account_setup_email, send_monthly_summaries],
    ids=lambda t: t.name,
)
def test_tasks_are_registered_with_retry_limit(task: Task[Any, Any]) -> None:
    # Worker chỉ nạp task trong `include`: quên khai module thì worker từ chối task từ API.
    celery_app.loader.import_default_modules()

    assert celery_app.tasks[task.name].max_retries == TASK_MAX_RETRIES


def test_beat_runs_monthly_summary_at_8am_on_first_day_vietnam_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    celery_app.loader.import_default_modules()
    entry = celery_app.conf.beat_schedule["monthly-summary"]
    schedule = entry["schedule"]
    zone = ZoneInfo(get_settings().timezone)

    # Beat gọi task theo tên: tên sai thì tới giờ worker báo task không tồn tại.
    assert entry["task"] == MONTHLY_SUMMARY_TASK == send_monthly_summaries.name
    assert MONTHLY_SUMMARY_TASK in celery_app.tasks
    assert entry.get("args", ()) == ()
    assert isinstance(schedule, crontab)
    # Không có result backend: không để Beat tự thêm lịch dọn kết quả (celery.backend_cleanup).
    assert celery_app.conf.result_expires is None
    # Lần chạy kế tiếp sau 08:00 ngày 1/11 là 08:00 ngày 1/12 giờ Việt Nam: Celery tính lịch theo
    # timezone của app, để UTC thì sẽ là 15:00 giờ Việt Nam.
    now = datetime(2026, 11, 1, 8, 0, 1, tzinfo=zone)
    monkeypatch.setattr(schedule, "nowfun", lambda: now)
    remaining = schedule.remaining_estimate(datetime(2026, 11, 1, 8, 0, tzinfo=zone))
    assert now + remaining == datetime(2026, 12, 1, 8, 0, tzinfo=zone)


def test_retry_countdown_doubles_each_attempt() -> None:
    assert [retry_countdown(n) for n in range(TASK_MAX_RETRIES)] == [
        TASK_RETRY_BACKOFF_SECONDS,
        TASK_RETRY_BACKOFF_SECONDS * 2,
        TASK_RETRY_BACKOFF_SECONDS * 4,
    ]


@pytest.mark.parametrize(
    "signal", [after_setup_logger, after_setup_task_logger], ids=["root", "task"]
)
def test_celery_loggers_follow_app_log_level(
    monkeypatch: pytest.MonkeyPatch, signal: Signal
) -> None:
    # Celery đặt mức log theo cờ --loglevel (mặc định WARNING) rồi phát signal; mức thật phải là
    # LOG_LEVEL, một chỗ cấu hình cho cả log của Celery và log của app.
    monkeypatch.setattr(get_settings(), "log_level", "DEBUG")
    logger = logging.getLogger(f"test.celery.{id(signal)}")
    logger.setLevel(logging.WARNING)

    signal.send(sender=None, logger=logger, loglevel=logging.WARNING)

    assert logger.level == logging.DEBUG
