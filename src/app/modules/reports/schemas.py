from collections.abc import Sequence
from datetime import date, datetime
from typing import Annotated, Any, Self

from fastapi import Query
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from app.core.constants import (
    REPORT_CONTENT_MAX_LENGTH,
    REPORT_CONTENT_MIN_LENGTH,
    REPORT_RECIPIENTS_MAX,
    REPORT_RECIPIENTS_MIN,
)
from app.core.pagination import DateRangePageParams
from app.core.validators import Id, NoNul, blank_to_none
from app.modules.reports.models import DailyReport, ReportRecipient
from app.modules.users.models import User


def _drop_duplicates(ids: list[int]) -> list[int]:
    # Gửi trùng id là cùng một người nhận; để nguyên thì insert trùng khóa chính, API trả 500.
    return list(dict.fromkeys(ids))


ReportContent = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=REPORT_CONTENT_MIN_LENGTH,
        max_length=REPORT_CONTENT_MAX_LENGTH,
    ),
    NoNul,
]
OptionalReportContent = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=REPORT_CONTENT_MAX_LENGTH),
    NoNul,
    AfterValidator(blank_to_none),
]
# Danh sách rỗng trả 422: không gửi cho ai thì bỏ field (hoặc null) để gửi cho tất cả.
RecipientIds = Annotated[
    list[Id],
    Field(min_length=REPORT_RECIPIENTS_MIN, max_length=REPORT_RECIPIENTS_MAX),
    AfterValidator(_drop_duplicates),
]


class RecipientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str


class ReportCreate(BaseModel):
    # Field lạ trả 422, để client biết dữ liệu đó không được lưu.
    model_config = ConfigDict(extra="forbid")

    report_date: date
    planned_work: ReportContent
    actual_work: ReportContent
    incomplete_reason: OptionalReportContent | None = None
    next_day_plan: ReportContent
    recipient_ids: RecipientIds | None = Field(
        default=None,
        description=(
            "Id người nhận, lấy từ GET /me/recipients. Không gửi field này (hoặc null) thì gửi "
            "cho tất cả; danh sách rỗng bị từ chối."
        ),
    )


class ReportSummaryOut(BaseModel):
    """Báo cáo không kèm người nhận: phần tử của lịch sử báo cáo, phần chung của các schema sau."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    report_date: date
    department_id: int
    planned_work: str
    actual_work: str
    incomplete_reason: str | None
    next_day_plan: str
    created_at: datetime
    updated_at: datetime


class ReportOut(ReportSummaryOut):
    recipients: list[RecipientOut]

    @field_validator("recipients", mode="before")
    @classmethod
    def _recipient_users(cls, value: Any) -> Any:
        # Bảng report_recipients chỉ giữ id; client cần biết tên, email người nhận. Chỉ bóc khi là
        # model: dữ liệu dạng dict (cache, truy vấn khác) để Pydantic tự validate, sai thì 422.
        if isinstance(value, list):
            return [item.recipient if isinstance(item, ReportRecipient) else item for item in value]
        return value


class ReportDepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str


class ReportRecipientOut(BaseModel):
    id: int
    full_name: str
    # Người nhận đã bị xóa vẫn hiện để giữ đúng lịch sử, nhưng ẩn email: email chỉ unique trên
    # user chưa xóa nên có thể đã thuộc về một tài khoản mới.
    email: str | None
    is_deleted: bool

    @classmethod
    def from_user(cls, user: User) -> Self:
        is_deleted = user.deleted_at is not None
        return cls(
            id=user.id,
            full_name=user.full_name,
            email=None if is_deleted else user.email,
            is_deleted=is_deleted,
        )


class ReportDetailOut(ReportSummaryOut):
    # Bộ phận lúc viết báo cáo, có thể khác bộ phận hiện tại của người viết.
    department: ReportDepartmentOut
    recipients: list[ReportRecipientOut]

    @classmethod
    def from_report(cls, report: DailyReport, recipients: Sequence[User]) -> Self:
        """`report` phải đã load sẵn `department`; `recipients` đã sắp theo tên."""
        return cls(
            **ReportSummaryOut.model_validate(report).model_dump(),
            department=ReportDepartmentOut.model_validate(report.department),
            recipients=[ReportRecipientOut.from_user(user) for user in recipients],
        )


ReportListQuery = Annotated[DateRangePageParams, Query()]
