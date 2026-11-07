"""Celery app: hàng đợi tác vụ nền (gửi email) trên Redis.

Chạy worker: `celery -A app.worker worker` (Docker Compose có sẵn service `worker`).
API chỉ đẩy task vào Redis qua `task.delay(...)`, không chờ worker xử lý.
"""

from typing import Any

from celery import Celery
from celery.signals import worker_init

from app import models as _models  # noqa: F401 (nạp đủ model trước khi SQLAlchemy nối quan hệ)
from app.core.config import get_settings
from app.core.constants import REDIS_TIMEOUT_SECONDS, TASK_RETRY_BACKOFF_SECONDS
from app.core.logging import configure_logging

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


def retry_countdown(retries: int) -> int:
    """Số giây chờ trước lần thử lại thứ `retries + 1` của task: 30s, 60s, 120s."""
    return int(TASK_RETRY_BACKOFF_SECONDS * 2**retries)
