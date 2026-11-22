"""Postman collection (docs/postman) khớp với route của app.

Endpoint mới chưa có trong collection, hay request trỏ tới route đã đổi tên, xóa thì test đỏ.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

COLLECTION_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "postman"
    / "daily-report.postman_collection.json"
)
BASE_URL = "{{baseUrl}}"
# Nhóm endpoint theo role: request phải gửi token của đúng role đó.
ROLE_TOKENS = {
    "/api/v1/admin/": "{{adminToken}}",
    "/api/v1/manager/": "{{managerToken}}",
    "/api/v1/me/reports": "{{userToken}}",
    "/api/v1/me/recipients": "{{userToken}}",
}


@pytest.fixture(scope="module")
def collection() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(COLLECTION_PATH.read_text(encoding="utf-8"))
    return data


def _requests(
    items: list[dict[str, Any]], auth: dict[str, Any] | None = None
) -> Iterator[tuple[dict[str, Any], dict[str, Any] | None]]:
    """Mọi request kèm auth có hiệu lực (của request, hoặc kế thừa từ folder)."""
    for item in items:
        item_auth = item.get("request", item).get("auth", auth)
        if "item" in item:
            yield from _requests(item["item"], item.get("auth", auth))
        else:
            yield item, item_auth


def _route(item: dict[str, Any]) -> tuple[str, str] | None:
    """(method, path theo Swagger) của request gọi API; None với request gọi dịch vụ khác."""
    url = item["request"]["url"]
    if url["host"] != [BASE_URL]:
        return None
    # Path param của Postman (`:report_id`) đổi về dạng Swagger (`{report_id}`).
    segments = [f"{{{s[1:]}}}" if s.startswith(":") else s for s in url["path"]]
    return item["request"]["method"], "/" + "/".join(segments)


def test_collection_covers_every_api_route(app: FastAPI, collection: dict[str, Any]) -> None:
    routes = {
        (method.upper(), path)
        for path, methods in app.openapi()["paths"].items()
        for method in methods
    }
    covered = {
        route for item, _ in _requests(collection["item"]) if (route := _route(item)) is not None
    }

    assert sorted(routes - covered) == []
    assert sorted(covered - routes) == []


def test_role_endpoints_send_token_of_that_role(collection: dict[str, Any]) -> None:
    wrong = []
    for item, auth in _requests(collection["item"]):
        route = _route(item)
        if route is None:
            continue
        expected = next(
            (token for prefix, token in ROLE_TOKENS.items() if route[1].startswith(prefix)), None
        )
        token = auth["bearer"][0]["value"] if auth and auth["type"] == "bearer" else None
        if expected is not None and token != expected:
            wrong.append(f"{item['name']}: {token}")

    assert wrong == []
