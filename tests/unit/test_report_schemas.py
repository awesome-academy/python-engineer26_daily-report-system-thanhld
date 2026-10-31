from datetime import UTC, date, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.reports.schemas import ReportOut

RECIPIENT = {"id": 7, "full_name": "Trần Thị Bình", "email": "binh@example.com"}


def report_data(**overrides: Any) -> dict[str, Any]:
    now = datetime(2026, 11, 9, 1, 30, tzinfo=UTC)
    data: dict[str, Any] = {
        "id": 1,
        "report_date": date(2026, 11, 9),
        "department_id": 2,
        "planned_work": "Làm API",
        "actual_work": "Xong API",
        "incomplete_reason": None,
        "next_day_plan": "Viết test",
        "recipients": [RECIPIENT],
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return data


def test_report_out_validates_from_plain_data() -> None:
    # Dữ liệu không đến từ model (cache, kết quả truy vấn dạng dict) vẫn dùng được ReportOut.
    report = ReportOut.model_validate(report_data())

    assert report.recipients[0].model_dump() == RECIPIENT


@pytest.mark.parametrize("recipients", [[{"id": 7}], None], ids=["missing-fields", "not-a-list"])
def test_report_out_rejects_malformed_recipients_as_validation_error(recipients: Any) -> None:
    with pytest.raises(ValidationError, match="recipients"):
        ReportOut.model_validate(report_data(recipients=recipients))
