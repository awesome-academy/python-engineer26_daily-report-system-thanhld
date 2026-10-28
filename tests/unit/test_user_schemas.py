import pytest
from pydantic import ValidationError

from app.core.constants import EMAIL_MAX_LENGTH, FULL_NAME_MAX_LENGTH, PASSWORD_MIN_LENGTH
from app.modules.users.schemas import UserCreate, UserProfileUpdate

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
        ("password", "matkhau@123"),
        ("password", "Mat khau 123"),
    ],
    ids=[
        "email-format",
        "email-too-long",
        "name-blank",
        "name-too-long",
        "password-too-short",
        "password-weak",
        "password-space-is-not-special",
    ],
)
def test_rejects_invalid_values(field: str, value: str) -> None:
    with pytest.raises(ValidationError) as error:
        UserCreate.model_validate(VALID | {field: value})

    assert error.value.errors()[0]["loc"] == (field,)


def test_password_accepts_non_ascii_letters_and_symbols() -> None:
    user = UserCreate.model_validate(VALID | {"password": "Mậtkhẩu 2026!"})

    assert user.password == "Mậtkhẩu 2026!"


@pytest.mark.parametrize(
    "phone", ["0912345678", "+84912345678", "123456789"], ids=["local", "e164", "shortest"]
)
def test_profile_update_accepts_phone(phone: str) -> None:
    assert UserProfileUpdate(phone=phone).phone == phone


@pytest.mark.parametrize(
    "phone",
    ["12345678", "+" + "1" * 16, "0912 345 678", "", "0912abc678"],
    ids=["too-short", "too-long", "inner-space", "empty", "letters"],
)
def test_profile_update_rejects_phone(phone: str) -> None:
    with pytest.raises(ValidationError):
        UserProfileUpdate(phone=phone)


def test_profile_update_dump_contains_only_sent_fields() -> None:
    data = UserProfileUpdate.model_validate({"phone": None})

    assert data.model_dump(exclude_unset=True) == {"phone": None}
