import pytest
from pydantic import ValidationError

from app.core.constants import EMAIL_MAX_LENGTH, FULL_NAME_MAX_LENGTH, PASSWORD_MIN_LENGTH
from app.modules.users.schemas import UserCreate

VALID = {"email": "an@example.com", "full_name": "Nguyễn Văn An", "password": "Matkhau@123"}


def test_full_name_is_trimmed_but_password_is_kept_as_typed() -> None:
    user = UserCreate.model_validate(
        VALID | {"full_name": "  Nguyễn Văn An  ", "password": " Matkhau@123 "}
    )

    assert user.full_name == "Nguyễn Văn An"
    assert user.password == " Matkhau@123 "


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("email", "khong-phai-email"),
        ("email", "a" * (EMAIL_MAX_LENGTH - len("@example.com") + 1) + "@example.com"),
        ("full_name", "   "),
        ("full_name", "a" * (FULL_NAME_MAX_LENGTH + 1)),
        ("password", "x" * (PASSWORD_MIN_LENGTH - 1)),
    ],
    ids=["email-format", "email-too-long", "name-blank", "name-too-long", "password-too-short"],
)
def test_rejects_invalid_values(field: str, value: str) -> None:
    with pytest.raises(ValidationError) as error:
        UserCreate.model_validate(VALID | {field: value})

    assert error.value.errors()[0]["loc"] == (field,)
