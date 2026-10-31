from collections.abc import Sequence
from datetime import date

from app.core.constants import REPORT_BACKDATE_DAYS
from app.core.exceptions import ConflictError, ErrorCode, UnprocessableError


class ReportAlreadyExistsError(ConflictError):
    code = ErrorCode.REPORT_ALREADY_EXISTS

    def __init__(self, report_date: date) -> None:
        super().__init__(
            f"Bạn đã tạo báo cáo cho ngày {report_date.isoformat()}.",
            details={"field": "report_date"},
        )


class ReportDateOutOfRangeError(UnprocessableError):
    code = ErrorCode.REPORT_DATE_OUT_OF_RANGE
    message = (
        f"Chỉ tạo được báo cáo cho hôm nay hoặc tối đa {REPORT_BACKDATE_DAYS} ngày trước, "
        "không tạo trước cho ngày tương lai."
    )

    def __init__(self, min_date: date, max_date: date) -> None:
        super().__init__(
            details={"field": "report_date", "min_date": min_date, "max_date": max_date}
        )


class InvalidRecipientError(UnprocessableError):
    code = ErrorCode.INVALID_RECIPIENT
    message = (
        "Người nhận phải là manager của bộ phận bạn. Lấy danh sách hợp lệ ở GET /me/recipients."
    )

    def __init__(self, invalid_ids: Sequence[int]) -> None:
        super().__init__(details={"field": "recipient_ids", "invalid_ids": list(invalid_ids)})


class NoRecipientError(UnprocessableError):
    # Khác INVALID_RECIPIENT (client chọn sai, sửa request là được): ở đây gửi lại kiểu gì cũng
    # lỗi, phải chờ admin xếp bộ phận, gán manager.
    code = ErrorCode.NO_RECIPIENT_AVAILABLE
    message = (
        "Chưa có ai nhận được báo cáo của bạn: bạn chưa thuộc bộ phận nào hoặc bộ phận chưa có "
        "manager. Liên hệ admin để được xếp bộ phận, gán manager."
    )
