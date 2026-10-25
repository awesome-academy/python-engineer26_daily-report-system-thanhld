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
