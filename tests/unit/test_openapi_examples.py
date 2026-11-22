"""Ví dụ trên Swagger: mọi request body, response có ví dụ, và ví dụ khớp với schema thật.

Duyệt OpenAPI của app, không liệt kê tay: endpoint mới thiếu ví dụ thì test đỏ.
"""

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

JSON = "application/json"
REF_PREFIX = "#/components/schemas/"


def _operations(schema: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (f"{method.upper()} {path}", operation)
        for path, methods in schema["paths"].items()
        for method, operation in methods.items()
    ]


def _has_example(schema: dict[str, Any], components: dict[str, Any]) -> bool:
    """Schema có ví dụ, hoặc Swagger ghép được ví dụ từ ví dụ của các phần (trang `Page[...]`)."""
    if "examples" in schema or "example" in schema:
        return True
    if "$ref" in schema:
        return _has_example(components[schema["$ref"].removeprefix(REF_PREFIX)], components)
    if schema.get("type") == "array":
        return _has_example(schema["items"], components)
    properties: dict[str, Any] = schema.get("properties", {})
    return bool(properties) and all(_has_example(p, components) for p in properties.values())


def test_every_json_request_and_response_has_example(app: FastAPI) -> None:
    schema = app.openapi()
    components = schema["components"]["schemas"]
    missing = []
    for name, operation in _operations(schema):
        body = operation.get("requestBody", {}).get("content", {}).get(JSON)
        if body is not None and not _has_example(body["schema"], components):
            missing.append(f"{name} request body")
        for status_code, response in operation["responses"].items():
            content = response.get("content", {}).get(JSON)
            if content is None:
                continue
            # Lỗi khai bằng error_responses có ví dụ ở response (mỗi mã lỗi một ví dụ).
            has_example = "examples" in content or _has_example(content["schema"], components)
            if not has_example:
                missing.append(f"{name} {status_code}")

    assert missing == []


def test_every_error_response_has_example_per_error(app: FastAPI) -> None:
    schema = app.openapi()
    missing = [
        f"{name} {status_code}"
        for name, operation in _operations(schema)
        for status_code, response in operation["responses"].items()
        if int(status_code) >= 400
        and not {"examples", "example"} & set(response.get("content", {}).get(JSON, {}))
    ]

    assert missing == []


def _model_examples() -> dict[type[BaseModel], list[dict[str, Any]]]:
    """Ví dụ khai ở `json_schema_extra` của mọi model của app (fixture `app` đã nạp app.main)."""
    found: dict[type[BaseModel], list[dict[str, Any]]] = {}
    pending = list(BaseModel.__subclasses__())
    while pending:
        model = pending.pop()
        pending.extend(model.__subclasses__())
        extra = model.model_config.get("json_schema_extra")
        if model.__module__.startswith("app.") and isinstance(extra, dict) and "examples" in extra:
            examples = extra["examples"]
            assert isinstance(examples, list), model.__name__
            found[model] = [example for example in examples if isinstance(example, dict)]
            assert len(found[model]) == len(examples), model.__name__
    return found


def _request_model_names(app: FastAPI) -> set[str]:
    schema = app.openapi()
    return {
        body["schema"]["$ref"].removeprefix(REF_PREFIX)
        for _, operation in _operations(schema)
        if (body := operation.get("requestBody", {}).get("content", {}).get(JSON)) is not None
    }


def test_schema_examples_are_valid_for_their_model(app: FastAPI) -> None:
    request_models = _request_model_names(app)
    models = _model_examples()
    assert {"ReportCreate", "ReportDetailOut", "PageMeta"} <= {model.__name__ for model in models}

    for model, examples in models.items():
        for example in examples:
            # Dữ liệu ví dụ đi qua đúng validate của model: sai kiểu, sai quy tắc thì lỗi ở đây.
            model.model_validate(example)
            fields = set(model.model_fields)
            if model.__name__ in request_models:
                # Body sửa từng phần chỉ gửi vài field; field thừa (gõ sai tên) vẫn bị bắt.
                assert set(example) <= fields, model.__name__
            else:
                # Response trả đủ mọi field: ví dụ thiếu field là ví dụ cũ chưa cập nhật.
                assert set(example) == fields, model.__name__


def test_swagger_description_explains_how_to_try(app: FastAPI) -> None:
    description = app.openapi()["info"]["description"]

    assert "Authorize" in description
    assert "daily-report seed" in description
