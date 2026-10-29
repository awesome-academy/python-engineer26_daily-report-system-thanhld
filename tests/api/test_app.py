import pytest
from httpx import AsyncClient


async def test_unknown_path_returns_error_format(client: AsyncClient) -> None:
    response = await client.get("/api/v1/khong-ton-tai")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "NOT_FOUND", "message": "Không tìm thấy đường dẫn.", "details": None}
    }


async def test_wrong_method_returns_error_format(client: AsyncClient) -> None:
    response = await client.post("/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


async def test_response_has_generated_request_id(client: AsyncClient) -> None:
    response = await client.get("/health")

    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32
    assert int(request_id, 16) >= 0


async def test_valid_incoming_request_id_is_kept(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "abc-123.xyz"})

    assert response.headers["X-Request-ID"] == "abc-123.xyz"


@pytest.mark.parametrize("bad_id", ["có dấu cách", "x" * 65, "line\nbreak"])
async def test_unsafe_incoming_request_id_is_replaced(client: AsyncClient, bad_id: str) -> None:
    response = await client.get("/health", headers={b"X-Request-ID": bad_id.encode("utf-8")})

    assert response.headers["X-Request-ID"] != bad_id
    assert len(response.headers["X-Request-ID"]) == 32


async def test_openapi_schema_is_available(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Daily Report API"


@pytest.mark.parametrize(
    ("path", "method", "status_code"),
    [
        ("/api/v1/auth/login", "post", "401"),
        ("/api/v1/auth/login", "post", "422"),
        ("/api/v1/me", "get", "401"),
        ("/api/v1/me/reports", "post", "403"),
        ("/api/v1/me/reports", "post", "409"),
        ("/api/v1/me/reports", "post", "422"),
    ],
)
async def test_openapi_documents_errors_with_common_format(
    client: AsyncClient, path: str, method: str, status_code: str
) -> None:
    schema = (await client.get("/openapi.json")).json()

    response = schema["paths"][path][method]["responses"][status_code]
    assert response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
