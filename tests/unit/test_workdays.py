from datetime import date

import pytest

from app.core.workdays import count_working_days, is_working_day

# Tháng 10/2026 bắt đầu thứ 5, có 9 ngày thứ 7, chủ nhật.
OCTOBER_FIRST = date(2026, 10, 1)
OCTOBER_LAST = date(2026, 10, 31)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 10, 5), True),  # thứ 2
        (date(2026, 10, 9), True),  # thứ 6
        (date(2026, 10, 10), False),  # thứ 7
        (date(2026, 10, 11), False),  # chủ nhật
    ],
)
def test_working_days_are_monday_to_friday(day: date, expected: bool) -> None:
    assert is_working_day(day) is expected


def test_count_working_days_of_month() -> None:
    assert count_working_days(OCTOBER_FIRST, OCTOBER_LAST) == 22


def test_count_working_days_includes_both_ends() -> None:
    assert count_working_days(date(2026, 10, 5), date(2026, 10, 9)) == 5
    assert count_working_days(date(2026, 10, 5), date(2026, 10, 5)) == 1


def test_count_working_days_is_zero_for_weekend_or_empty_range() -> None:
    assert count_working_days(date(2026, 10, 10), date(2026, 10, 11)) == 0
    assert count_working_days(date(2026, 10, 9), date(2026, 10, 5)) == 0
