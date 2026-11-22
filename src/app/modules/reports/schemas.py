from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
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
from app.core.validators import Id, Keyword, NoNul, blank_to_none, drop_duplicates
from app.modules.departments.models import Department
from app.modules.reports.models import DailyReport, ReportRecipient
from app.modules.users.models import User

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
    AfterValidator(drop_duplicates),
]

# Ví dụ trên Swagger (request, response, lỗi): báo cáo của an.nguyen@example.com (id 5, bộ phận DEV
# id 1) gửi cho manager.dev@example.com (id 2), khớp dữ liệu seed khi seed vào DB trống.
EXAMPLE_REPORT_DATE = date(2026, 11, 9)
_REPORT_CONTENT_EXAMPLE: dict[str, Any] = {
    "report_date": EXAMPLE_REPORT_DATE.isoformat(),
    "planned_work": "Làm API hồ sơ cá nhân",
    "actual_work": "Xong xem, sửa hồ sơ",
    "incomplete_reason": "Đổi mật khẩu chờ chốt quy tắc",
    "next_day_plan": "Đổi mật khẩu",
}
_REPORT_SUMMARY_EXAMPLE: dict[str, Any] = {
    "id": 128,
    **_REPORT_CONTENT_EXAMPLE,
    "department_id": 1,
    "created_at": "2026-11-09T10:15:00Z",
    "updated_at": "2026-11-09T10:15:00Z",
}
_RECIPIENT_EXAMPLE: dict[str, Any] = {
    "id": 2,
    "full_name": "Trần Minh Quân",
    "email": "manager.dev@example.com",
}
_DEPARTMENT_EXAMPLE: dict[str, Any] = {"id": 1, "code": "DEV", "name": "Phòng Phát triển"}
_RECIPIENT_USER_EXAMPLE: dict[str, Any] = {**_RECIPIENT_EXAMPLE, "is_deleted": False}
_AUTHOR_EXAMPLE: dict[str, Any] = {
    "id": 5,
    "full_name": "Nguyễn Văn An",
    "email": "an.nguyen@example.com",
    "is_deleted": False,
}
_REPORT_DETAIL_EXAMPLE: dict[str, Any] = {
    **_REPORT_SUMMARY_EXAMPLE,
    "department": _DEPARTMENT_EXAMPLE,
    "recipients": [_RECIPIENT_USER_EXAMPLE],
}


class RecipientOut(BaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_extra={"examples": [_RECIPIENT_EXAMPLE]}
    )

    id: int
    full_name: str
    email: str


class ReportCreate(BaseModel):
    # Field lạ trả 422, để client biết dữ liệu đó không được lưu.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{**_REPORT_CONTENT_EXAMPLE, "recipient_ids": [_RECIPIENT_EXAMPLE["id"]]}]
        },
    )

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

    model_config = ConfigDict(
        from_attributes=True, json_schema_extra={"examples": [_REPORT_SUMMARY_EXAMPLE]}
    )

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
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{**_REPORT_SUMMARY_EXAMPLE, "recipients": [_RECIPIENT_EXAMPLE]}]
        }
    )

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
    model_config = ConfigDict(
        from_attributes=True, json_schema_extra={"examples": [_DEPARTMENT_EXAMPLE]}
    )

    id: int
    code: str
    name: str


class ReportUserOut(BaseModel):
    """Người viết hoặc người nhận của một báo cáo."""

    model_config = ConfigDict(json_schema_extra={"examples": [_AUTHOR_EXAMPLE]})

    id: int
    full_name: str
    # Người đã bị xóa vẫn hiện để giữ đúng lịch sử, nhưng ẩn email: email chỉ unique trên user
    # chưa xóa nên có thể đã thuộc về một tài khoản mới.
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
    model_config = ConfigDict(json_schema_extra={"examples": [_REPORT_DETAIL_EXAMPLE]})

    # Bộ phận lúc viết báo cáo, có thể khác bộ phận hiện tại của người viết.
    department: ReportDepartmentOut
    recipients: list[ReportUserOut]

    @classmethod
    def from_report(cls, report: DailyReport, recipients: Sequence[User]) -> Self:
        """`report` phải đã load sẵn `department`; `recipients` đã sắp theo tên."""
        return cls(
            **ReportSummaryOut.model_validate(report).model_dump(),
            department=ReportDepartmentOut.model_validate(report.department),
            recipients=[ReportUserOut.from_user(user) for user in recipients],
        )


ReportListQuery = Annotated[DateRangePageParams, Query()]


class ReportSort(StrEnum):
    """Thứ tự danh sách báo cáo của manager; dấu `-` là giảm dần."""

    REPORT_DATE_DESC = "-report_date"
    REPORT_DATE = "report_date"
    AUTHOR_NAME = "author_name"
    AUTHOR_NAME_DESC = "-author_name"


class ManagerReportListParams(DateRangePageParams):
    keyword: Annotated[
        Keyword | None, Field(description="Tìm theo họ tên người viết (không dấu)")
    ] = None
    department_id: Annotated[
        Id | None, Field(description="Chỉ lấy báo cáo của bộ phận này (bộ phận tôi quản lý)")
    ] = None
    sort: ReportSort = Field(
        default=ReportSort.REPORT_DATE_DESC,
        description="Ngày báo cáo hoặc họ tên người viết, dấu `-` là giảm dần",
    )


class ManagerReportSummaryOut(ReportSummaryOut):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{**_REPORT_SUMMARY_EXAMPLE, "author": _AUTHOR_EXAMPLE}]}
    )

    author: ReportUserOut

    @classmethod
    def from_report(cls, report: DailyReport) -> Self:
        """`report` phải đã load sẵn `author`."""
        return cls(
            **ReportSummaryOut.model_validate(report).model_dump(),
            author=ReportUserOut.from_user(report.author),
        )


class ManagerReportDetailOut(ReportDetailOut):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{**_REPORT_DETAIL_EXAMPLE, "author": _AUTHOR_EXAMPLE}]}
    )

    author: ReportUserOut

    @classmethod
    def from_report(cls, report: DailyReport, recipients: Sequence[User]) -> Self:
        """Như `ReportDetailOut.from_report`, `report` load sẵn cả `author`."""
        return cls(
            **ReportDetailOut.from_report(report, recipients).model_dump(),
            author=ReportUserOut.from_user(report.author),
        )


@dataclass(frozen=True)
class ReportExportParams:
    """Tham số export (M5) đã kiểm tra: `department_id` (nếu có) nằm trong phạm vi manager."""

    report_date: date
    department_id: int | None = None


class ReportExportRow(BaseModel):
    """Một dòng của file export (M5): nhân viên trong một bộ phận, kèm báo cáo nếu đã nộp."""

    department: ReportDepartmentOut
    # Người viết đã bị xóa không có email, như danh sách báo cáo M3.
    author: ReportUserOut
    report: ReportSummaryOut | None

    @classmethod
    def from_models(cls, department: Department, author: User, report: DailyReport | None) -> Self:
        return cls(
            department=ReportDepartmentOut.model_validate(department),
            author=ReportUserOut.from_user(author),
            report=ReportSummaryOut.model_validate(report) if report is not None else None,
        )
