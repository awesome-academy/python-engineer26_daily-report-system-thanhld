from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PageParams, paginate


def numbers_up_to(last: int) -> Select[int]:
    numbers = func.generate_series(1, last).table_valued("value").render_derived()
    return select(numbers.c.value).order_by(numbers.c.value)


async def test_paginate_returns_requested_page_and_total(db_session: AsyncSession) -> None:
    statement = numbers_up_to(45)

    rows, total = await paginate(db_session, statement, PageParams(page=3, page_size=20))

    assert total == 45
    assert list(rows) == [41, 42, 43, 44, 45]


async def test_paginate_past_last_page_returns_empty_rows(db_session: AsyncSession) -> None:
    statement = numbers_up_to(5)

    rows, total = await paginate(db_session, statement, PageParams(page=2, page_size=20))

    assert total == 5
    assert list(rows) == []
