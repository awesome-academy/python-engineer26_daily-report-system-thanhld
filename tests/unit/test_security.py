import pytest

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


async def test_hash_password_uses_argon2_and_verifies() -> None:
    password_hash = await hash_password("Matkhau@123")

    assert password_hash.startswith("$argon2")
    assert await verify_password("Matkhau@123", password_hash)
    assert not await verify_password("matkhau@123", password_hash)


async def test_same_password_hashes_differently_each_time() -> None:
    assert await hash_password("Matkhau@123") != await hash_password("Matkhau@123")


def test_access_token_round_trip_keeps_claims() -> None:
    token = create_access_token(user_id=42, role="ADMIN", token_version=3)

    claims = decode_access_token(token.token)

    assert (claims.user_id, claims.role, claims.token_version) == (42, "ADMIN", 3)
    assert token.expires_in == get_settings().access_token_expire_minutes * 60


def test_each_access_token_has_unique_id() -> None:
    first = decode_access_token(create_access_token(user_id=1, role="USER", token_version=0).token)
    second = decode_access_token(create_access_token(user_id=1, role="USER", token_version=0).token)

    assert first.jti != second.jti


def test_tampered_token_is_rejected() -> None:
    token = create_access_token(user_id=1, role="USER", token_version=0).token
    header, payload, signature = token.split(".")

    with pytest.raises(UnauthorizedError):
        decode_access_token(f"{header}.{payload}.{signature[::-1]}")
