import pytest
from jinja2 import UndefinedError

from app.core.config import get_settings
from app.modules.notifications.models import EmailTemplate
from app.modules.notifications.rendering import render_email


def test_render_test_email_fills_subject_text_and_html() -> None:
    email = render_email(EmailTemplate.TEST, {"requested_at": "08:30:00 06/11/2026"})

    app_name = get_settings().app_name
    assert email.subject == f"[{app_name}] Email thử"
    assert "08:30:00 06/11/2026" in email.text
    assert "08:30:00 06/11/2026" in email.html
    assert email.html.startswith("<!doctype html>")
    assert f"<title>{email.subject}</title>" in email.html


@pytest.mark.parametrize("template", list(EmailTemplate))
def test_every_template_has_subject_text_and_html(template: EmailTemplate) -> None:
    # Thêm mẫu mới vào EmailTemplate mà thiếu file thì test này đỏ, không đợi tới lúc worker gửi.
    email = render_email(template, {"requested_at": "x"})

    assert email.subject
    assert email.text
    assert email.html


def test_render_escapes_html_but_not_plain_text() -> None:
    email = render_email(EmailTemplate.TEST, {"requested_at": "<b>&</b>"})

    assert "&lt;b&gt;&amp;&lt;/b&gt;" in email.html
    assert "<b>&</b>" in email.text


def test_render_keeps_subject_on_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    # Biến trong tiêu đề chứa xuống dòng không được tạo thêm dòng header.
    settings = get_settings()
    monkeypatch.setattr(settings, "app_name", "Daily\r\nBcc: x@example.com")

    email = render_email(EmailTemplate.TEST, {"requested_at": "x"})

    assert email.subject == "[Daily Bcc: x@example.com] Email thử"


def test_render_rejects_missing_variable() -> None:
    with pytest.raises(UndefinedError, match="requested_at"):
        render_email(EmailTemplate.TEST, {})
