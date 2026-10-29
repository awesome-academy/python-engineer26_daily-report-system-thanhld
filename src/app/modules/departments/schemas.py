import re
from datetime import datetime
from typing import Annotated

from fastapi import Query
from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints, field_validator

from app.core import messages
from app.core.constants import (
    DEPARTMENT_CODE_MAX_LENGTH,
    DEPARTMENT_CODE_MIN_LENGTH,
    DEPARTMENT_CODE_PATTERN,
    DEPARTMENT_DESCRIPTION_MAX_LENGTH,
    DEPARTMENT_NAME_MAX_LENGTH,
    DEPARTMENT_NAME_MIN_LENGTH,
    KEYWORD_MAX_LENGTH,
)
from app.core.pagination import PageParams
from app.core.validators import reject_null


def _check_department_code(code: str) -> str:
    # Kiểm tra trước khi chuyển chữ hoa: upper() đổi ngầm ký tự Unicode ("ß" thành "SS", chữ i
    # không chấm U+0131 thành "I"), vừa lách quy tắc chữ không dấu, vừa làm mã dài hơn max_length
    # đã kiểm tra (DB báo lỗi, API trả 500).
    if not re.fullmatch(DEPARTMENT_CODE_PATTERN, code):
        raise ValueError(messages.DEPARTMENT_CODE_INVALID)
    return code


# Mã chuẩn hóa về chữ hoa, nên " dev " và "DEV" là một mã. Chỉ ASCII nên upper() không đổi độ dài.
DepartmentCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=DEPARTMENT_CODE_MIN_LENGTH,
        max_length=DEPARTMENT_CODE_MAX_LENGTH,
    ),
    AfterValidator(_check_department_code),
    AfterValidator(str.upper),
]
DepartmentName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=DEPARTMENT_NAME_MIN_LENGTH,
        max_length=DEPARTMENT_NAME_MAX_LENGTH,
    ),
]
DepartmentDescription = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=DEPARTMENT_DESCRIPTION_MAX_LENGTH)
]
Keyword = Annotated[str, StringConstraints(strip_whitespace=True, max_length=KEYWORD_MAX_LENGTH)]


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class DepartmentCreate(BaseModel):
    code: DepartmentCode
    name: DepartmentName
    description: DepartmentDescription | None = None


class DepartmentUpdate(BaseModel):
    """Cập nhật từng phần: field không gửi thì giữ nguyên, `null` xóa mô tả.

    Field lạ bị từ chối (422) thay vì bỏ qua, để client biết thay đổi đó không có hiệu lực.
    """

    model_config = ConfigDict(extra="forbid")

    code: DepartmentCode | None = None
    name: DepartmentName | None = None
    description: DepartmentDescription | None = None

    _not_null = field_validator("code", "name")(reject_null)


class DepartmentListParams(PageParams):
    keyword: Keyword | None = None


DepartmentListQuery = Annotated[DepartmentListParams, Query()]
