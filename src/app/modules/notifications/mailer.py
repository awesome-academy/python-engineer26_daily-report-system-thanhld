"""Gửi email qua SMTP bằng smtplib (chạy trong Celery worker, code đồng bộ)."""

import smtplib
import ssl
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Protocol

from app.core.config import Settings
from app.core.constants import SMTP_TIMEOUT_SECONDS
from app.modules.notifications.rendering import RenderedEmail


class Mailer(Protocol):
    def send(self, to_email: str, email: RenderedEmail) -> None: ...


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_message(self, to_email: str, email: RenderedEmail) -> EmailMessage:
        sender = self.settings.mail_from
        message = EmailMessage()
        message["From"] = Address(display_name=sender.name, addr_spec=sender.email)
        message["To"] = to_email
        message["Subject"] = email.subject
        message["Date"] = formatdate()
        message["Message-ID"] = make_msgid(domain=sender.email.rpartition("@")[2])
        # Bản text cho trình đọc mail không hiển thị HTML; bản HTML là phần chính.
        message.set_content(email.text)
        message.add_alternative(email.html, subtype="html")
        return message

    def send(self, to_email: str, email: RenderedEmail) -> None:
        """Gửi một email. Lỗi kết nối, lỗi SMTP được ném ra để task thử lại."""
        message = self.build_message(to_email, email)
        settings = self.settings
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS)
        try:
            if settings.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username is not None and settings.smtp_password is not None:
                smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            smtp.send_message(message)
        finally:
            _quit(smtp)


def _quit(smtp: smtplib.SMTP) -> None:
    # Server đã nhận thư thì lỗi ở lệnh QUIT không được làm task thử lại, nếu không sẽ gửi trùng.
    try:
        smtp.quit()
    except (smtplib.SMTPException, OSError):
        smtp.close()
