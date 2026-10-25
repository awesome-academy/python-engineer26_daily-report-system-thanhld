import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_requires_own_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(environment="production")


def test_production_accepts_custom_jwt_secret() -> None:
    settings = Settings(environment="production", jwt_secret_key="s" * 48)

    assert settings.json_logs


def test_local_uses_readable_logs() -> None:
    assert not Settings(environment="local").json_logs
