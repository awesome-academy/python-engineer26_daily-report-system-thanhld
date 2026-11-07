from app.core.config import get_settings
from app.core.constants import REDIS_TIMEOUT_SECONDS, TASK_MAX_RETRIES, TASK_RETRY_BACKOFF_SECONDS
from app.modules.notifications.tasks import send_email
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


def test_send_email_task_is_registered_with_retry_limit() -> None:
    # Worker chỉ nạp task trong `include`: quên khai module thì worker từ chối task từ API.
    celery_app.loader.import_default_modules()

    assert celery_app.tasks[send_email.name].max_retries == TASK_MAX_RETRIES


def test_retry_countdown_doubles_each_attempt() -> None:
    assert [retry_countdown(n) for n in range(TASK_MAX_RETRIES)] == [
        TASK_RETRY_BACKOFF_SECONDS,
        TASK_RETRY_BACKOFF_SECONDS * 2,
        TASK_RETRY_BACKOFF_SECONDS * 4,
    ]
