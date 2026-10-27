import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.constants import JWT_SECRET_MIN_LENGTH, Environment


def test_production_requires_own_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(environment=Environment.PRODUCTION)


def test_production_accepts_custom_jwt_secret() -> None:
    settings = Settings(
        environment=Environment.PRODUCTION, jwt_secret_key="s" * JWT_SECRET_MIN_LENGTH
    )

    assert settings.json_logs


def test_rejects_jwt_secret_shorter_than_hs256_minimum() -> None:
    with pytest.raises(ValidationError, match="jwt_secret_key"):
        Settings(jwt_secret_key="s" * (JWT_SECRET_MIN_LENGTH - 1))


def test_local_uses_readable_logs() -> None:
    assert not Settings(environment=Environment.LOCAL).json_logs


def test_rejects_unknown_environment() -> None:
    with pytest.raises(ValidationError, match="environment"):
        Settings(environment="prod")  # type: ignore[arg-type]
