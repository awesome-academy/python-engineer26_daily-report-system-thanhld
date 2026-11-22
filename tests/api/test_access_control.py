"""Kiểm kê xác thực, phân quyền theo role của mọi endpoint (OWASP API2, API5).

Danh sách endpoint lấy từ router của app như khi FastAPI sinh Swagger, không liệt kê tay: endpoint
thêm sau tự vào kiểm tra. Endpoint không cần đăng nhập phải có trong PUBLIC_ENDPOINTS, để mở một
endpoint công khai là quyết định có chủ đích chứ không phải do quên dependency. Endpoint còn lại
thiếu token trả 401, role ngoài nhóm trả 403, trước khi xét tham số, body hay dữ liệu.

Phạm vi dữ liệu theo bộ phận (ngoài phạm vi trả 404, OWASP API1) kiểm tra ở test_department_scope.py
và test của từng endpoint (báo cáo, nhân viên ngoài phạm vi).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.health import router as health_router
from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.constants import ID_MIN
from app.modules.users.models import UserRole
from tests.factories import auth_headers, create_user
from tests.helpers import PATH_PARAM, api_routes, dependency_calls, endpoint_id

API = get_settings().api_v1_prefix
PUBLIC_ENDPOINTS = {
    ("GET", "/health"),
    ("POST", f"{API}/auth/login"),
    ("POST", f"{API}/auth/refresh"),
    ("POST", f"{API}/auth/setup-password"),
}
# Role duy nhất được gọi endpoint có tiền tố này, như các nhóm endpoint trong docs/api-design.md.
# Endpoint không khớp tiền tố nào (/me, /me/avatar, /auth/logout...) mở cho mọi role đã đăng nhập.
ROLE_PREFIXES = {
    f"{API}/admin/": UserRole.ADMIN,
    f"{API}/manager/": UserRole.MANAGER,
    f"{API}/me/reports": UserRole.USER,
    f"{API}/me/recipients": UserRole.USER,
}


# Hai router create_app() gắn vào app; test đối chiếu Swagger bên dưới chặn router bị sót.
ENDPOINTS = {
    (method, path): route
    for path, route in api_routes(health_router, api_router)
    for method in route.methods or ()
}
PROTECTED_ENDPOINTS = sorted(set(ENDPOINTS) - PUBLIC_ENDPOINTS)


def required_role(path: str) -> UserRole | None:
    return next((role for prefix, role in ROLE_PREFIXES.items() if path.startswith(prefix)), None)


WRONG_ROLE_CALLS = [
    pytest.param((method, path), role, id=f"{endpoint_id((method, path))} as {role}")
    for method, path in PROTECTED_ENDPOINTS
    if (required := required_role(path)) is not None
    for role in UserRole
    if role != required
]


def url(path: str) -> str:
    # Tham số trên URL lấy id hợp lệ bất kỳ: lỗi 401, 403 phải có trước khi xét tới nó.
    return PATH_PARAM.sub(str(ID_MIN), path)


async def test_endpoints_cover_every_documented_operation(client: AsyncClient) -> None:
    # Router gắn thẳng vào app (không qua api_router) thì không nằm trong ENDPOINTS mà vẫn lên
    # Swagger: đối chiếu để không endpoint nào lọt khỏi kiểm tra.
    paths = (await client.get("/openapi.json")).json()["paths"]
    documented = {
        (method.upper(), path) for path, operations in paths.items() for method in operations
    }

    assert documented == set(ENDPOINTS)


def test_only_listed_endpoints_are_public() -> None:
    public = {
        endpoint
        for endpoint, route in ENDPOINTS.items()
        if get_current_user not in set(dependency_calls(route.dependant))
    }

    assert public == PUBLIC_ENDPOINTS


def test_role_prefixes_match_endpoints() -> None:
    # Tiền tố gõ sai thì WRONG_ROLE_CALLS thiếu endpoint mà test vẫn xanh.
    for prefix in ROLE_PREFIXES:
        assert any(path.startswith(prefix) for _, path in PROTECTED_ENDPOINTS), prefix


@pytest.mark.parametrize("endpoint", PROTECTED_ENDPOINTS, ids=endpoint_id)
async def test_protected_endpoint_requires_token(
    client: AsyncClient, endpoint: tuple[str, str]
) -> None:
    method, path = endpoint

    response = await client.request(method, url(path))

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize(("endpoint", "role"), WRONG_ROLE_CALLS)
async def test_endpoint_rejects_role_outside_its_group(
    client: AsyncClient, db_session: AsyncSession, endpoint: tuple[str, str], role: UserRole
) -> None:
    method, path = endpoint
    user = await create_user(db_session, role=role)

    response = await client.request(method, url(path), headers=auth_headers(user))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
