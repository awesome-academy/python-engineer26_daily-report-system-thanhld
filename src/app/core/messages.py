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
DATE_RANGE_INVALID = "date_to phải cùng ngày hoặc sau date_from."

# Import nhân viên từ Excel (A4): lỗi theo dòng trong `details` của IMPORT_VALIDATION_FAILED.
IMPORT_FAILED = "File có {count} lỗi, chưa tạo tài khoản nào. Sửa các dòng bị lỗi rồi tải lên lại."
IMPORT_HEADER_MISMATCH = 'Dòng tiêu đề phải giống file mẫu: cột {column} là "{header}".'
IMPORT_NO_DATA_ROWS = "File chưa có dòng dữ liệu nào dưới dòng tiêu đề."
IMPORT_TOO_MANY_ROWS = "File có quá {max_rows} dòng dữ liệu, hãy chia thành nhiều file."
IMPORT_PHONE_NOT_TEXT = "Số điện thoại phải nhập ở ô định dạng chữ (Text): ô số làm mất số 0 đầu."
IMPORT_DATE_INVALID = "Phải là ô kiểu ngày, hoặc chữ dạng {date_format}."
IMPORT_EMAIL_DUPLICATED = "Email trùng với dòng {row}."
IMPORT_DEPARTMENT_NOT_FOUND = "Không có bộ phận mã này, hoặc bộ phận đã bị xóa."
