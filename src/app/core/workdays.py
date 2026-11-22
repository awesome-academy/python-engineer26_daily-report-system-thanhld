"""Ngày làm việc (WORKING_ISO_WEEKDAYS): một định nghĩa cho code Python và câu SQL."""

from datetime import date, timedelta

from sqlalchemy import ColumnElement, func
from sqlalchemy.orm import InstrumentedAttribute

from app.core.constants import WORKING_ISO_WEEKDAYS


def is_working_day(day: date) -> bool:
    return day.isoweekday() in WORKING_ISO_WEEKDAYS


def count_working_days(first: date, last: date) -> int:
    """Số ngày làm việc từ `first` đến `last`, tính cả hai đầu; `first` sau `last` thì 0."""
    days = (last - first).days + 1
    return sum(is_working_day(first + timedelta(days=offset)) for offset in range(days))


def is_working_day_sql(
    day: ColumnElement[date] | InstrumentedAttribute[date],
) -> ColumnElement[bool]:
    """Điều kiện SQL cùng nghĩa với `is_working_day` cho một cột ngày."""
    return func.extract("isodow", day).in_(WORKING_ISO_WEEKDAYS)
