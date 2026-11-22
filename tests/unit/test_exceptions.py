from collections.abc import AsyncIterator
from typing import Any

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
    UnprocessableError,
    error_responses,
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


@pytest.mark.parametrize(
    "namespace",
    [{}, {"code": ErrorCode.VALIDATION_ERROR}],
    ids=["missing-code", "validation-error"],
)
def test_unprocessable_error_requires_own_code(namespace: dict[str, object]) -> None:
    # VALIDATION_ERROR có details là danh sách lỗi theo field; lỗi nghiệp vụ 422 có details là dict
    # nên phải có mã riêng để client phân biệt.
    with pytest.raises(TypeError, match="BusinessError"):
        type("BusinessError", (UnprocessableError,), namespace)


class FieldConflictError(ConflictError):
    code = ErrorCode.EMAIL_ALREADY_EXISTS

    def __init__(self, field: str) -> None:
        super().__init__(details={"field": field})


def _examples(responses: dict[int | str, dict[str, Any]], status_code: int) -> dict[str, Any]:
    examples: dict[str, Any] = responses[status_code]["content"]["application/json"]["examples"]
    return examples


def test_error_responses_example_comes_from_error_instance() -> None:
    error = FieldConflictError("email")

    responses = error_responses(error)

    assert responses[409]["model"].__name__ == "ErrorResponse"
    assert _examples(responses, 409) == {
        "EMAIL_ALREADY_EXISTS: email": {
            "summary": "EMAIL_ALREADY_EXISTS: email",
            "value": {
                "error": {
                    "code": "EMAIL_ALREADY_EXISTS",
                    "message": error.message,
                    "details": {"field": "email"},
                }
            },
        }
    }


def test_error_responses_common_status_uses_generic_example() -> None:
    responses = error_responses(401, 422)

    assert _examples(responses, 401)["UNAUTHORIZED"]["value"]["error"] == {
        "code": "UNAUTHORIZED",
        "message": UnauthorizedError.message,
        "details": None,
    }
    validation = _examples(responses, 422)["VALIDATION_ERROR"]["value"]["error"]
    assert validation["code"] == "VALIDATION_ERROR"
    assert isinstance(validation["details"], list)


def test_error_responses_groups_examples_by_status() -> None:
    responses = error_responses(
        404, NotFoundError(details={"field": "user_id"}), FieldConflictError("code")
    )

    assert set(responses) == {404, 409}
    assert list(_examples(responses, 404)) == ["NOT_FOUND", "NOT_FOUND: user_id"]


def test_error_responses_numbers_different_errors_with_same_name() -> None:
    responses = error_responses(ConflictError("Trùng lần một."), ConflictError("Trùng lần hai."))

    assert list(_examples(responses, 409)) == ["CONFLICT", "CONFLICT (2)"]


def test_error_responses_documents_headers_of_error() -> None:
    # Header lỗi trả kèm (WWW-Authenticate của 401) phải có trên Swagger để client biết mà đọc.
    responses = error_responses(401, FieldConflictError("email"))

    assert responses[401]["headers"] == {
        "WWW-Authenticate": {
            "description": "Kèm lỗi `UNAUTHORIZED`, ví dụ `Bearer`.",
            "schema": {"type": "string"},
        }
    }
    assert "headers" not in responses[409]


def test_error_responses_rejects_same_error_twice() -> None:
    with pytest.raises(ValueError, match="hai lần"):
        error_responses(FieldConflictError("email"), FieldConflictError("email"))


@pytest.mark.parametrize("status_code", [400, 409, 413, 429])
def test_error_responses_requires_error_instance_for_business_status(status_code: int) -> None:
    # Các status này chỉ có lỗi nghiệp vụ riêng của từng endpoint, không có ví dụ chung đúng mã.
    with pytest.raises(ValueError, match=f"HTTP {status_code}"):
        error_responses(status_code)
