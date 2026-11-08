"""Celery app: hàng đợi tác vụ nền (gửi email) trên Redis.

Chạy worker: `celery -A app.worker worker` (Docker Compose có sẵn service `worker`).
API chỉ đẩy task vào Redis qua `task.delay(...)`, không chờ worker xử lý.
"""

import asyncio
import logging
from typing import Any

import structlog
from celery import Celery, Task
from celery.signals import after_setup_logger, after_setup_task_logger, worker_init
from kombu.exceptions import OperationalError

from app import models as _models  # noqa: F401 (nạp đủ model trước khi SQLAlchemy nối quan hệ)
from app.core.config import get_settings
from app.core.constants import REDIS_TIMEOUT_SECONDS, TASK_MAX_RETRIES, TASK_RETRY_BACKOFF_SECONDS
from app.core.logging import configure_logging

logger = structlog.get_logger(__name__)

settings = get_settings()

celery_app = Celery(
    "daily_report",
    # Cùng DB Redis với API (blacklist token, đếm đăng nhập sai); key của Celery có tên riêng
    # (`celery`, `_kombu.*`, `unacked*`) nên không lẫn với key `auth:*`.
    broker=settings.redis_url,
    include=["app.modules.notifications.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    # Không có result backend: API đẩy task rồi thôi, kết quả gửi email ghi ở bảng email_logs.
    task_ignore_result=True,
    # Ack sau khi task chạy xong: worker bị dừng giữa chừng (restart container) thì task được giao
    # lại thay vì mất. Đổi lại, task có thể chạy lại, nên task phải chịu được chạy hai lần.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Redis treo thì `.delay()` báo lỗi sau vài giây, không chờ vô hạn.
    broker_transport_options={
        "socket_timeout": REDIS_TIMEOUT_SECONDS,
        "socket_connect_timeout": REDIS_TIMEOUT_SECONDS,
    },
    broker_connection_retry_on_startup=True,
    # structlog tự in ra stdout; Celery mặc định chuyển stdout thành log WARNING, in lặp hai lần.
    worker_redirect_stdouts=False,
    timezone=settings.timezone,
    enable_utc=True,
)


@worker_init.connect
def _configure_worker_logging(**_: Any) -> None:
    # Chạy ở process chính trước khi tạo process con, process con kế thừa cấu hình.
    configure_logging(settings.log_level, json_logs=settings.json_logs)


@after_setup_logger.connect
@after_setup_task_logger.connect
def _use_app_log_level(logger: logging.Logger, **_: Any) -> None:
    # Log của Celery theo LOG_LEVEL như log của app, không theo cờ --loglevel (mặc định WARNING):
    # một chỗ đặt mức log cho cả worker.
    logger.setLevel(settings.log_level)


def retry_countdown(retries: int) -> int:
    """Số giây chờ trước lần thử lại thứ `retries + 1` của task: 30s, 60s, 120s."""
    return int(TASK_RETRY_BACKOFF_SECONDS * 2**retries)


def retry_or_give_up(task: Task[Any, Any], exc: Exception) -> None:
    """Còn lượt thì hẹn chạy lại task (ném `Retry`); hết lượt thì trả về để task ghi FAILED."""
    retries = task.request.retries
    if retries >= TASK_MAX_RETRIES:
        return
    countdown = retry_countdown(retries)
    logger.warning(
        "task_retry",
        task=task.name,
        task_id=task.request.id,
        attempt=retries + 1,
        countdown=countdown,
        error=repr(exc),
    )
    raise task.retry(exc=exc, countdown=countdown)


async def enqueue_task(task: Task[Any, Any], *args: Any) -> None:
    """Đẩy task vào Redis từ code async, gọi sau khi commit.

    `delay()` là lệnh chặn (kết nối, gửi tới Redis) nên chạy ở thread khác để không chặn event
    loop. Redis lỗi thì chỉ ghi log: dữ liệu đã commit, request vẫn thành công, mất một tác vụ nền
    (email) còn hơn báo lỗi cho thao tác đã lưu xong.
    """
    try:
        await asyncio.to_thread(task.delay, *args)
    except OperationalError:
        logger.exception("task_enqueue_failed", task=task.name)
