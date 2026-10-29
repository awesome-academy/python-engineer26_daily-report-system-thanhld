from datetime import date, datetime
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from app.core.constants import (
    BIGINT_MAX,
    ID_MIN,
    REPORT_CONTENT_MAX_LENGTH,
    REPORT_CONTENT_MIN_LENGTH,
    REPORT_RECIPIENTS_MAX,
)
from app.core.validators import NoNul, blank_to_none


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
RecipientIds = Annotated[
    list[Annotated[int, Field(ge=ID_MIN, le=BIGINT_MAX)]],
    Field(min_length=1, max_length=REPORT_RECIPIENTS_MAX),
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
        description="Id người nhận, lấy từ GET /me/recipients. Bỏ trống thì gửi cho tất cả.",
    )


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_date: date
    department_id: int
    planned_work: str
    actual_work: str
    incomplete_reason: str | None
    next_day_plan: str
    recipients: list[RecipientOut]
    created_at: datetime
    updated_at: datetime

    @field_validator("recipients", mode="before")
    @classmethod
    def _recipient_users(cls, value: Any) -> Any:
        # Bảng report_recipients chỉ giữ id; client cần biết tên, email người nhận.
        return [item.recipient for item in value]
