from datetime import date

import pytest

from app.modules.reports.monthly_summary import (
    EmployeeSummary,
    month_end,
    previous_month,
    resolve_month,
)

TODAY = date(2026, 11, 22)


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 11, 1), date(2026, 10, 1)),
        (date(2026, 11, 30), date(2026, 10, 1)),
        (date(2026, 1, 1), date(2025, 12, 1)),
        (date(2026, 3, 31), date(2026, 2, 1)),
    ],
)
def test_previous_month_is_first_day_of_month_before(today: date, expected: date) -> None:
    assert previous_month(today) == expected


@pytest.mark.parametrize(
    ("first", "expected"),
    [
        (date(2026, 10, 1), date(2026, 10, 31)),
        (date(2026, 11, 1), date(2026, 11, 30)),
        (date(2026, 2, 1), date(2026, 2, 28)),
        (date(2028, 2, 1), date(2028, 2, 29)),
    ],
)
def test_month_end(first: date, expected: date) -> None:
    assert month_end(first) == expected


def test_resolve_month_defaults_to_previous_month() -> None:
    assert resolve_month(None, TODAY) == date(2026, 10, 1)


@pytest.mark.parametrize(
    ("month", "expected"),
    [("2026-10", date(2026, 10, 1)), ("2025-12", date(2025, 12, 1))],
)
def test_resolve_month_accepts_finished_month(month: str, expected: date) -> None:
    assert resolve_month(month, TODAY) == expected


@pytest.mark.parametrize("month", ["2026-13", "10/2026", "2026-10-01", "", "tháng 10"])
def test_resolve_month_rejects_wrong_format(month: str) -> None:
    with pytest.raises(ValueError, match="không đúng dạng YYYY-MM"):
        resolve_month(month, TODAY)


@pytest.mark.parametrize("month", ["2026-11", "2026-12", "2027-01"])
def test_resolve_month_rejects_month_not_finished(month: str) -> None:
    # Thống kê tháng đang chạy sẽ tính cả ngày chưa tới, và giữ dedup_key của tháng đó: lần chạy
    # đúng lịch ngày 1 tháng sau sẽ không gửi nữa.
    with pytest.raises(ValueError, match="chưa kết thúc"):
        resolve_month(month, TODAY)


def test_employee_summary_missing_days_and_rate() -> None:
    row = EmployeeSummary("Nguyễn Văn An", is_active=True, submitted_days=20, working_days=22)

    assert row.missing_days == 2
    assert row.rate == "91%"
