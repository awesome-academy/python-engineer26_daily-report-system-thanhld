import json
from collections.abc import Iterator

import pytest
import structlog

from app.core.logging import configure_logging


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    yield
    configure_logging("INFO", json_logs=False)


def test_json_logs_render_one_json_object_per_line(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_logs=True)

    structlog.get_logger("test").info("report_created", report_id=7)

    record = json.loads(capsys.readouterr().out)
    assert record["event"] == "report_created"
    assert record["report_id"] == 7
    assert record["level"] == "info"


def test_level_filters_lower_messages(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING", json_logs=True)

    structlog.get_logger("test").info("hidden")

    assert capsys.readouterr().out == ""


def fail_with_secret_in_locals() -> None:
    password = "Matkhau@123"  # noqa: F841 (biến cục bộ cần có trong frame bị lỗi)
    raise RuntimeError("boom")


@pytest.mark.parametrize("json_logs", [True, False], ids=["json", "console"])
def test_exception_log_has_traceback_without_local_variables(
    capsys: pytest.CaptureFixture[str], json_logs: bool
) -> None:
    configure_logging("INFO", json_logs=json_logs)

    try:
        fail_with_secret_in_locals()
    except RuntimeError:
        structlog.get_logger("test").exception("unhandled_error")

    output = capsys.readouterr().out
    assert "fail_with_secret_in_locals" in output
    assert "Matkhau@123" not in output
