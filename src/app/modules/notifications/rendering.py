"""Dựng nội dung email từ template Jinja2."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from app.core.config import get_settings
from app.modules.notifications.models import EmailTemplate

_environment = Environment(
    loader=PackageLoader("app.modules.notifications", "templates"),
    # Escape HTML cho body.html (tên, nội dung báo cáo do người dùng nhập); file .txt giữ nguyên.
    autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=False),
    # Thiếu biến thì báo lỗi, không gửi email có chỗ trống.
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    text: str
    html: str


def render_email(template: EmailTemplate, context: Mapping[str, Any]) -> RenderedEmail:
    values = {"app_name": get_settings().app_name, **context}
    subject = _environment.get_template(f"{template}/subject.txt").render(values)
    # Tiêu đề là một dòng header: bỏ xuống dòng (biến chứa "\n" không chèn được header khác).
    values["subject"] = " ".join(subject.split())
    return RenderedEmail(
        subject=values["subject"],
        text=_environment.get_template(f"{template}/body.txt").render(values),
        html=_environment.get_template(f"{template}/body.html").render(values),
    )
