"""Phân trang dùng chung: tham số query, response {data, meta} và hàm paginate()."""

from collections.abc import Sequence
from typing import Annotated, Any, Self

from fastapi import Query
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DEFAULT_PAGE_SIZE, MAX_PAGE, MAX_PAGE_SIZE


class PageParams(BaseModel):
    page: int = Field(default=1, ge=1, le=MAX_PAGE, description="Trang, bắt đầu từ 1")
    page_size: int = Field(
        default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Số bản ghi mỗi trang"
    )

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


PageQuery = Annotated[PageParams, Query()]


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int


class Page[T](BaseModel):
    data: list[T]
    meta: PageMeta

    @classmethod
    def build(cls, data: Sequence[T], *, total: int, params: PageParams) -> Self:
        return cls(
            data=list(data),
            meta=PageMeta(page=params.page, page_size=params.page_size, total=total),
        )


async def paginate(
    session: AsyncSession, statement: Select[Any], params: PageParams
) -> tuple[Sequence[Any], int]:
    """Trả về (bản ghi của trang hiện tại, tổng số bản ghi khớp điều kiện)."""
    count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
    total = await session.scalar(count_statement) or 0
    rows = await session.scalars(statement.limit(params.page_size).offset(params.offset))
    return rows.all(), total
