from typing import Any

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


REPORT_CONTEXT = {
    "recipient_name": "Trần Quản Lý",
    "author_name": "Nguyễn Văn An",
    "department_name": "Phát triển",
    "report_date": "06/11/2026",
    "planned_work": "Làm API đăng nhập",
    "actual_work": "Xong API đăng nhập\nViết test",
    "incomplete_reason": None,
    "next_day_plan": "Làm API hồ sơ",
}
# Context mẫu đủ biến của từng mẫu email.
TEMPLATE_CONTEXTS: dict[EmailTemplate, dict[str, Any]] = {
    EmailTemplate.TEST: {"requested_at": "x"},
    EmailTemplate.REPORT_CREATED: REPORT_CONTEXT,
}


def test_every_template_has_sample_context() -> None:
    assert set(TEMPLATE_CONTEXTS) == set(EmailTemplate)


@pytest.mark.parametrize("template", list(EmailTemplate))
def test_every_template_has_subject_text_and_html(template: EmailTemplate) -> None:
    # Thêm mẫu mới vào EmailTemplate mà thiếu file thì test này đỏ, không đợi tới lúc worker gửi.
    email = render_email(template, TEMPLATE_CONTEXTS[template])

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


def test_render_report_created_email() -> None:
    email = render_email(EmailTemplate.REPORT_CREATED, REPORT_CONTEXT)

    app_name = get_settings().app_name
    assert email.subject == f"[{app_name}] Báo cáo ngày 06/11/2026 của Nguyễn Văn An"
    for body in (email.text, email.html):
        assert "Trần Quản Lý" in body
        assert "Phát triển" in body
        assert "Làm API đăng nhập" in body
        assert "Làm API hồ sơ" in body
        # Không có lý do chưa hoàn thành thì bỏ cả mục.
        assert "Lý do chưa hoàn thành" not in body
    assert "Xong API đăng nhập\nViết test" in email.text
    # Giữ xuống dòng của nội dung báo cáo trong bản HTML.
    assert "white-space:pre-line" in email.html


def test_render_report_created_shows_incomplete_reason_and_escapes_content() -> None:
    context = {**REPORT_CONTEXT, "incomplete_reason": "Chờ <script>alert(1)</script>"}

    email = render_email(EmailTemplate.REPORT_CREATED, context)

    assert "Lý do chưa hoàn thành" in email.text
    assert "Chờ <script>alert(1)</script>" in email.text
    # Nội dung do nhân viên nhập: bản HTML phải escape, không chèn được thẻ.
    assert "Chờ &lt;script&gt;alert(1)&lt;/script&gt;" in email.html
    assert "<script>" not in email.html
