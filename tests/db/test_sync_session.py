from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.core.database import SYNC_DRIVER, sync_database_url, sync_session


def test_sync_database_url_keeps_database_and_switches_driver() -> None:
    url = sync_database_url("postgresql+asyncpg://u:p@db:5432/daily_report")

    assert url.drivername == SYNC_DRIVER
    assert url.render_as_string(hide_password=False) == (
        f"{SYNC_DRIVER}://u:p@db:5432/daily_report"
    )


def test_sync_session_connects_to_configured_database(engine: AsyncEngine) -> None:
    # Celery worker dùng session này; phải trỏ đúng DATABASE_URL (ở đây là database test).
    with sync_session() as session:
        database = session.execute(text("SELECT current_database()")).scalar_one()

    assert database == make_url(get_settings().database_url).database
