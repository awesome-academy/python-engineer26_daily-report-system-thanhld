from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
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
    token = create_access_token(user_id=42, role="ADMIN", token_version=3, session_id="abc")

    claims = decode_access_token(token.token)

    assert (claims.user_id, claims.role, claims.token_version, claims.session_id) == (
        42,
        "ADMIN",
        3,
        "abc",
    )
    assert token.expires_in == get_settings().access_token_expire_minutes * 60
    assert claims.expires_at - datetime.now(UTC) <= timedelta(seconds=token.expires_in)


def test_each_access_token_has_unique_id() -> None:
    first = create_access_token(user_id=1, role="USER", token_version=0, session_id="s")
    second = create_access_token(user_id=1, role="USER", token_version=0, session_id="s")

    assert decode_access_token(first.token).jti != decode_access_token(second.token).jti


def test_tampered_token_is_rejected() -> None:
    token = create_access_token(user_id=1, role="USER", token_version=0, session_id="s").token
    header, payload, signature = token.split(".")

    with pytest.raises(UnauthorizedError):
        decode_access_token(f"{header}.{payload}.{signature[::-1]}")


def test_refresh_token_round_trip_keeps_claims() -> None:
    token = create_refresh_token(user_id=42, token_version=3)

    claims = decode_refresh_token(token.token)

    assert (claims.user_id, claims.token_version, claims.jti) == (42, 3, token.jti)
    expected_expiry = datetime.now(UTC) + timedelta(days=get_settings().refresh_token_expire_days)
    assert abs(token.expires_at - expected_expiry) < timedelta(seconds=5)


def test_access_and_refresh_tokens_are_not_interchangeable() -> None:
    access = create_access_token(user_id=1, role="USER", token_version=0, session_id="s").token
    refresh = create_refresh_token(user_id=1, token_version=0).token

    with pytest.raises(UnauthorizedError):
        decode_refresh_token(access)
    with pytest.raises(UnauthorizedError):
        decode_access_token(refresh)
