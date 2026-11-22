"""Giới hạn dung lượng body của mọi request (OWASP API4: tiêu thụ tài nguyên không giới hạn)."""

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.exceptions import RequestTooLargeError


class BodySizeLimitMiddleware:
    """Body lớn hơn `max_bytes` thì trả 413 `REQUEST_TOO_LARGE`, không đọc tiếp.

    FastAPI đọc hết body trước khi chạy dependency xác thực và trước khi endpoint upload kiểm tra
    dung lượng file (`read_upload`): JSON vào RAM, file multipart ra file tạm. Không chặn ở đây thì
    request chưa đăng nhập cũng làm đầy RAM, ổ đĩa được.

    Không dùng `max_body_size` có sẵn của Starlette: FastAPI không nhận tham số này, và khi endpoint
    không đọc body thì middleware đó trả lỗi dạng chữ, không theo format lỗi chung.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Khai báo trước dung lượng: từ chối ngay, không nhận phần body nào.
        content_length = Headers(scope=scope).get("content-length", "")
        if content_length.isdigit() and int(content_length) > self.max_bytes:
            await RequestTooLargeError(self.max_bytes).to_response()(scope, receive, send)
            return

        received = 0

        async def receive_with_limit() -> Message:
            # Body gửi từng đoạn (không có Content-Length): đếm dần, quá giới hạn thì dừng đọc. Lỗi
            # ném ra trong lúc FastAPI đọc body, exception handler đổi thành response 413.
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestTooLargeError(self.max_bytes)
            return message

        await self.app(scope, receive_with_limit, send)
