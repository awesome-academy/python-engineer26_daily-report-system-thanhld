from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field

from app.core.exceptions import (
    AppError,
    ConflictError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    register_exception_handlers,
)


class ItemIn(BaseModel):
    name: str = Field(min_length=1)


def build_app() -> FastAPI:
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/errors/{kind}")
    async def raise_error(kind: str) -> None:
        errors: dict[str, AppError] = {
            "app": AppError(),
            "unauthorized": UnauthorizedError(),
            "forbidden": ForbiddenError(),
            "not-found": NotFoundError("Không tìm thấy báo cáo."),
            "conflict": ConflictError(details={"field": "email"}),
        }
        raise errors[kind]

    @test_app.post("/items")
    async def create_item(item: ItemIn) -> ItemIn:
        return item

    @test_app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("unexpected")

    return test_app


@pytest.fixture
async def http() -> AsyncIterator[AsyncClient]:
    # raise_app_exceptions=False để nhận response 500 thay vì exception trong test.
    transport = ASGITransport(app=build_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.parametrize(
    ("kind", "status_code", "code", "message"),
    [
        ("app", 400, "BAD_REQUEST", "Yêu cầu không hợp lệ."),
        ("unauthorized", 401, "UNAUTHORIZED", UnauthorizedError.message),
        ("forbidden", 403, "FORBIDDEN", ForbiddenError.message),
        ("not-found", 404, "NOT_FOUND", "Không tìm thấy báo cáo."),
        ("conflict", 409, "CONFLICT", "Dữ liệu bị trùng."),
    ],
)
async def test_app_errors_use_common_format(
    http: AsyncClient, kind: str, status_code: int, code: str, message: str
) -> None:
    response = await http.get(f"/errors/{kind}")

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["message"] == message


async def test_app_error_keeps_details(http: AsyncClient) -> None:
    response = await http.get("/errors/conflict")

    assert response.json()["error"]["details"] == {"field": "email"}


async def test_validation_error_lists_invalid_fields(http: AsyncClient) -> None:
    response = await http.post("/items", json={"name": ""})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert [detail["field"] for detail in error["details"]] == ["body.name"]


async def test_unexpected_error_hides_internal_details(http: AsyncClient) -> None:
    response = await http.get("/boom")

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "Hệ thống đang gặp sự cố, vui lòng thử lại sau.",
        "details": None,
    }


def test_app_error_accepts_custom_code() -> None:
    error = AppError("Sai định dạng file.", code=ErrorCode.VALIDATION_ERROR)

    assert error.code == ErrorCode.VALIDATION_ERROR
    assert str(error) == "Sai định dạng file."
