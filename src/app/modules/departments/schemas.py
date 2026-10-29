import re
from datetime import datetime
from typing import Annotated

from fastapi import Query
from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints, field_validator

from app.core.constants import (
    DEPARTMENT_CODE_MAX_LENGTH,
    DEPARTMENT_CODE_PATTERN,
    DEPARTMENT_DESCRIPTION_MAX_LENGTH,
    DEPARTMENT_NAME_MAX_LENGTH,
    DEPARTMENT_NAME_MIN_LENGTH,
    KEYWORD_MAX_LENGTH,
)
from app.core.pagination import PageParams


def _check_department_code(code: str) -> str:
    # Kiểm tra sau khi trim, upper: pattern của StringConstraints chạy trên chuỗi gốc.
    if not re.fullmatch(DEPARTMENT_CODE_PATTERN, code):
        msg = "Mã bộ phận chỉ gồm chữ cái không dấu, chữ số, dấu gạch ngang và dấu gạch dưới."
        raise ValueError(msg)
    return code


# Mã chuẩn hóa về chữ hoa, nên " dev " và "DEV" là một mã.
DepartmentCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, max_length=DEPARTMENT_CODE_MAX_LENGTH),
    AfterValidator(_check_department_code),
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

    @field_validator("code", "name")
    @classmethod
    def _not_null(cls, value: str | None) -> str | None:
        # Chỉ chạy khi client gửi field này: mã, tên bắt buộc nên không được xóa bằng null.
        if value is None:
            msg = "Không được để trống."
            raise ValueError(msg)
        return value


class DepartmentListParams(PageParams):
    keyword: Keyword | None = None


DepartmentListQuery = Annotated[DepartmentListParams, Query()]
