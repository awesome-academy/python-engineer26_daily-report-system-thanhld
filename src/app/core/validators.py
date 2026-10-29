"""Validator Pydantic dùng chung cho schema của các module."""

from app.core import messages


def reject_null[T](value: T | None) -> T:
    """Field bắt buộc trong schema cập nhật từng phần: không gửi thì giữ nguyên, gửi null thì 422.

    Dùng với `field_validator`, ví dụ `_not_null = field_validator("name")(reject_null)`. Validator
    chỉ chạy khi client có gửi field, nên field bỏ trống vẫn mang nghĩa "không đổi".
    """
    if value is None:
        raise ValueError(messages.NOT_NULL)
    return value
