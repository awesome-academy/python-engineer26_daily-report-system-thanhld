"""Giới hạn dung lượng body của mọi request (OWASP API4: tiêu thụ tài nguyên không giới hạn)."""

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.exceptions import RequestTooLargeError


class BodySizeLimitMiddleware:
    """Body lớn hơn `max_bytes` thì trả 413 `REQUEST_TOO_LARGE`, không đọc tiếp.

    FastAPI đọc hết body trước khi chạy dependency xác thực và trước khi endpoint upload kiểm tra
    dung lượng file (`read_upload`): JSON vào RAM, file multipart ra file tạm. Không chặn ở đây thì
    request chưa đăng nhập cũng làm đầy RAM, ổ đĩa được.

    Không dùng `RequestBodyLimitMiddleware` có sẵn của Starlette: khi endpoint không đọc body, nó
    trả 413 dạng chữ, không theo format lỗi chung.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Khai báo trước dung lượng: từ chối ngay, không nhận phần body nào.
        if declared_length(scope) > self.max_bytes:
            await RequestTooLargeError(self.max_bytes).to_response()(scope, receive, send)
            return

        received = 0
        response_started = False

        async def send_marking_start(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        async def receive_with_limit() -> Message:
            # Body gửi từng đoạn (không có Content-Length): đếm dần, quá giới hạn thì dừng đọc. Lỗi
            # ném ra trong lúc FastAPI đọc body, exception handler đổi thành response 413.
            nonlocal received
            message = await receive()
            # Response đã bắt đầu gửi thì không trả 413 được nữa, ném lỗi chỉ làm ngắt response giữa
            # chừng. Lúc này endpoint đã chạy mà không cần body: chỉ còn Starlette đọc bỏ phần body
            # còn lại trong lúc gửi StreamingResponse, để biết client ngắt kết nối.
            if message["type"] == "http.request" and not response_started:
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestTooLargeError(self.max_bytes)
            return message

        await self.app(scope, receive_with_limit, send_marking_start)


def declared_length(scope: Scope) -> int:
    """Dung lượng ghi ở header Content-Length; không có, không phải số thì 0 (vẫn đếm byte)."""
    try:
        return int(Headers(scope=scope).get("content-length", ""))
    except ValueError:
        return 0
