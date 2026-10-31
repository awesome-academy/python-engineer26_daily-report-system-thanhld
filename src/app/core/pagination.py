"""Phân trang, lọc theo khoảng ngày dùng chung: tham số query, response {data, meta}, paginate()."""

from collections.abc import Sequence
from datetime import date
from typing import Annotated, Any, Self

from fastapi import Query
from pydantic import BaseModel, Field, ValidationInfo, field_validator
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import messages
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


class DateRange(BaseModel):
    """Lọc theo khoảng ngày, tính cả hai đầu; bỏ trống đầu nào thì không giới hạn đầu đó."""

    date_from: date | None = Field(default=None, description="Từ ngày, tính cả ngày này")
    date_to: date | None = Field(default=None, description="Đến ngày, tính cả ngày này")

    @field_validator("date_to")
    @classmethod
    def _not_before_date_from(cls, value: date | None, info: ValidationInfo) -> date | None:
        date_from = info.data.get("date_from")
        if value is not None and date_from is not None and value < date_from:
            raise ValueError(messages.DATE_RANGE_INVALID)
        return value


class DateRangePageParams(PageParams, DateRange):
    """Danh sách theo ngày có phân trang: lịch sử báo cáo của tôi (U3), báo cáo của manager (M3).

    Repository nhận nguyên object này; danh sách cần thêm bộ lọc thì kế thừa thêm field.
    """


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
