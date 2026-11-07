import smtplib
import ssl
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from email.message import EmailMessage

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.constants import SMTP_TIMEOUT_SECONDS
from app.modules.notifications.mailer import SmtpMailer
from app.modules.notifications.rendering import RenderedEmail

EMAIL = RenderedEmail(subject="Tiêu đề", text="Nội dung", html="<p>Nội dung</p>")


@dataclass
class FakeSMTP:
    """Thay smtplib.SMTP: ghi lại lệnh đã gọi; lệnh có trong `fail_on` thì ném lỗi tương ứng."""

    host: str
    port: int
    timeout: float
    fail_on: dict[str, Exception]
    calls: list[str] = field(default_factory=list)
    messages: list[EmailMessage] = field(default_factory=list)

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if name in self.fail_on:
            raise self.fail_on[name]

    def starttls(self, context: ssl.SSLContext) -> None:
        self._call("starttls")

    def login(self, user: str, password: str) -> None:
        self._call(f"login:{user}:{password}")

    def send_message(self, message: EmailMessage) -> None:
        self._call("send_message")
        self.messages.append(message)

    def quit(self) -> None:
        self._call("quit")

    def close(self) -> None:
        self._call("close")


@dataclass
class SMTPStub:
    """Các kết nối mailer đã mở; `fail_on` áp dụng cho kết nối mở sau đó."""

    servers: list[FakeSMTP] = field(default_factory=list)
    fail_on: dict[str, Exception] = field(default_factory=dict)

    def connect(self, host: str, port: int, timeout: float) -> FakeSMTP:
        server = FakeSMTP(host, port, timeout, fail_on=self.fail_on)
        self.servers.append(server)
        return server


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> SMTPStub:
    stub = SMTPStub()
    monkeypatch.setattr(smtplib, "SMTP", stub.connect)
    return stub


def test_send_delivers_text_and_html_with_headers(smtp: SMTPStub) -> None:
    settings = Settings(smtp_host="mail.local", smtp_port=2525)

    SmtpMailer(settings).send("an@example.com", EMAIL)

    [server] = smtp.servers
    assert (server.host, server.port, server.timeout) == ("mail.local", 2525, SMTP_TIMEOUT_SECONDS)
    assert server.calls == ["send_message", "quit"]
    [message] = server.messages
    assert message["To"] == "an@example.com"
    assert message["From"] == str(settings.mail_from)
    assert message["Subject"] == "Tiêu đề"
    assert message["Message-ID"].endswith("@example.com>")
    assert message["Date"]
    text_part = message.get_body(preferencelist=("plain",))
    html_part = message.get_body(preferencelist=("html",))
    assert text_part is not None
    assert html_part is not None
    assert text_part.get_content().strip() == "Nội dung"
    assert html_part.get_content().strip() == "<p>Nội dung</p>"


def test_send_uses_starttls_and_login_when_configured(smtp: SMTPStub) -> None:
    settings = Settings(
        smtp_starttls=True, smtp_username="mailer", smtp_password=SecretStr("bi-mat")
    )

    SmtpMailer(settings).send("an@example.com", EMAIL)

    assert smtp.servers[0].calls == ["starttls", "login:mailer:bi-mat", "send_message", "quit"]


def test_send_encodes_non_ascii_sender_name(smtp: SMTPStub) -> None:
    settings = Settings(mail_from="Báo cáo ngày <bao-cao@example.com>")  # type: ignore[arg-type]

    SmtpMailer(settings).send("an@example.com", EMAIL)

    raw = smtp.servers[0].messages[0].as_bytes()
    # Header chỉ được chứa ASCII: tên tiếng Việt mã hóa theo RFC 2047, đọc lại vẫn đúng.
    from_line = next(line for line in raw.splitlines() if line.startswith(b"From:"))
    assert from_line.isascii()
    parsed = message_from_bytes(raw, policy=policy.default)
    [sender] = parsed["From"].addresses
    assert (sender.display_name, sender.addr_spec) == ("Báo cáo ngày", "bao-cao@example.com")


def test_send_raises_and_quits_when_server_rejects(smtp: SMTPStub) -> None:
    smtp.fail_on["send_message"] = smtplib.SMTPDataError(451, b"try later")

    with pytest.raises(smtplib.SMTPDataError):
        SmtpMailer(Settings()).send("an@example.com", EMAIL)

    assert smtp.servers[0].calls == ["send_message", "quit"]


def test_send_ignores_quit_error_after_server_accepted(smtp: SMTPStub) -> None:
    # Lỗi ở QUIT mà ném ra thì task thử lại, người nhận nhận hai email.
    smtp.fail_on["quit"] = smtplib.SMTPServerDisconnected()

    SmtpMailer(Settings()).send("an@example.com", EMAIL)

    assert smtp.servers[0].calls == ["send_message", "quit", "close"]


def test_send_raises_when_server_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(host: str, port: int, timeout: float) -> FakeSMTP:
        raise ConnectionRefusedError

    monkeypatch.setattr(smtplib, "SMTP", refuse)

    with pytest.raises(ConnectionRefusedError):
        SmtpMailer(Settings()).send("an@example.com", EMAIL)
