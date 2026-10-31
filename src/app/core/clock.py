"""Thời điểm theo múi giờ nghiệp vụ (Settings.timezone), không theo giờ của máy chủ."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def local_date(moment: datetime) -> date:
    """Ngày theo giờ Việt Nam của một thời điểm (DB lưu UTC): 18:00 UTC đã là ngày hôm sau."""
    return moment.astimezone(ZoneInfo(get_settings().timezone)).date()


def local_today() -> date:
    """Hôm nay theo giờ Việt Nam: máy chủ chạy UTC thì 00:30 sáng ở Việt Nam vẫn là hôm qua."""
    return local_date(datetime.now(UTC))
