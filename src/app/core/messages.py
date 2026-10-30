"""Thông báo lỗi validate (422) dùng trong schema.

Lỗi nghiệp vụ (404, 409…) khai message trong class lỗi của module, không đặt ở đây.
"""

NOT_NULL = "Không được để trống."
NUL_CHARACTER = "Không được chứa ký tự NUL (\\x00)."
PASSWORD_TOO_WEAK = (
    "Mật khẩu phải có chữ thường, chữ hoa, chữ số và ký tự đặc biệt; còn thiếu: {missing}."  # noqa: S105 (thông báo lỗi, không phải mật khẩu)
)
NEW_PASSWORD_SAME_AS_CURRENT = "Mật khẩu mới phải khác mật khẩu hiện tại."  # noqa: S105 (thông báo lỗi)
DEPARTMENT_CODE_INVALID = (
    "Mã bộ phận chỉ gồm chữ cái không dấu, chữ số, dấu gạch ngang và dấu gạch dưới."
)
