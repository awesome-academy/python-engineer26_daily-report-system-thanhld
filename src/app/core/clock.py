"""Thời điểm theo múi giờ nghiệp vụ (Settings.timezone), không theo giờ của máy chủ."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, Date, cast, func
from sqlalchemy.orm import InstrumentedAttribute

from app.core.config import get_settings


def local_datetime(moment: datetime) -> datetime:
    """Thời điểm theo giờ Việt Nam (DB lưu UTC), để hiển thị: 01:30 UTC là 08:30 giờ Việt Nam."""
    return moment.astimezone(ZoneInfo(get_settings().timezone))


def local_date(moment: datetime) -> date:
    """Ngày theo giờ Việt Nam của một thời điểm (DB lưu UTC): 18:00 UTC đã là ngày hôm sau."""
    return local_datetime(moment).date()


def local_date_sql(
    moment: ColumnElement[datetime] | InstrumentedAttribute[datetime],
) -> ColumnElement[date]:
    """Như `local_date` nhưng trong SQL, cho cột thời điểm (timestamptz) cần so theo từng dòng."""
    return cast(func.timezone(get_settings().timezone, moment), Date)


def local_day_start(day: date) -> datetime:
    """0 giờ ngày `day` theo giờ Việt Nam, để so với cột thời điểm (UTC) theo ngày Việt Nam."""
    return datetime.combine(day, time.min, tzinfo=ZoneInfo(get_settings().timezone))


def local_today() -> date:
    """Hôm nay theo giờ Việt Nam: máy chủ chạy UTC thì 00:30 sáng ở Việt Nam vẫn là hôm qua."""
    return local_date(datetime.now(UTC))
