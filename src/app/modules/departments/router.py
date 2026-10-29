from fastapi import APIRouter, status

from app.api.deps import IdPath
from app.core.exceptions import error_responses
from app.core.pagination import Page, PageQuery
from app.modules.departments.dependencies import DepartmentServiceDep
from app.modules.departments.schemas import (
    DepartmentCreate,
    DepartmentListQuery,
    DepartmentManagerOut,
    DepartmentMemberOut,
    DepartmentOut,
    DepartmentUpdate,
    ManagerAssign,
)

# Include vào nhóm /admin (api/v1.py): role ADMIN được kiểm tra ở nhóm, 401, 403 khai ở nhóm.
admin_department_router = APIRouter(prefix="/departments", tags=["Admin: bộ phận"])


@admin_department_router.get(
    "",
    summary="Danh sách bộ phận",
    description="Tìm theo mã hoặc tên (không phân biệt hoa thường, không dấu), sắp theo mã.",
    responses=error_responses(status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def list_departments(
    params: DepartmentListQuery, service: DepartmentServiceDep
) -> Page[DepartmentOut]:
    departments, total = await service.list_departments(params)
    return Page[DepartmentOut].build(
        [DepartmentOut.model_validate(department) for department in departments],
        total=total,
        params=params,
    )


@admin_department_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Tạo bộ phận",
    description="Mã bộ phận được chuyển thành chữ hoa, không trùng với bộ phận chưa bị xóa.",
    responses=error_responses(status.HTTP_409_CONFLICT, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def create_department(data: DepartmentCreate, service: DepartmentServiceDep) -> DepartmentOut:
    return DepartmentOut.model_validate(await service.create_department(data))


@admin_department_router.get(
    "/{department_id}",
    summary="Xem bộ phận",
    responses=error_responses(status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def get_department(department_id: IdPath, service: DepartmentServiceDep) -> DepartmentOut:
    return DepartmentOut.model_validate(await service.get_department(department_id))


@admin_department_router.patch(
    "/{department_id}",
    summary="Sửa bộ phận",
    description="Cập nhật từng phần: field không gửi thì giữ nguyên, `null` xóa mô tả.",
    responses=error_responses(
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)
async def update_department(
    department_id: IdPath, data: DepartmentUpdate, service: DepartmentServiceDep
) -> DepartmentOut:
    return DepartmentOut.model_validate(await service.update_department(department_id, data))


@admin_department_router.delete(
    "/{department_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xóa bộ phận",
    description=(
        "Xóa mềm. Bộ phận còn thành viên thì nhận 409 `DEPARTMENT_NOT_EMPTY`; "
        "liên kết manager của bộ phận bị gỡ cùng lúc xóa."
    ),
    responses=error_responses(
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)
async def delete_department(department_id: IdPath, service: DepartmentServiceDep) -> None:
    await service.delete_department(department_id)


@admin_department_router.get(
    "/{department_id}/members",
    summary="Xem thành viên bộ phận",
    description="Thành viên là user thuộc bộ phận, kèm `is_manager` để chọn người gán manager.",
    responses=error_responses(status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def list_department_members(
    department_id: IdPath, params: PageQuery, service: DepartmentServiceDep
) -> Page[DepartmentMemberOut]:
    return await service.list_members(department_id, params)


@admin_department_router.post(
    "/{department_id}/managers",
    summary="Gán manager cho bộ phận",
    description=(
        "Chỉ gán được tài khoản role MANAGER đang hoạt động. Một bộ phận có nhiều manager, "
        "một manager quản lý nhiều bộ phận. Gán lại người đã là manager không lỗi, trả về "
        "thời điểm gán lần đầu."
    ),
    responses=error_responses(status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def assign_department_manager(
    department_id: IdPath, data: ManagerAssign, service: DepartmentServiceDep
) -> DepartmentManagerOut:
    return await service.assign_manager(department_id, data.user_id)


@admin_department_router.delete(
    "/{department_id}/managers/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Gỡ manager khỏi bộ phận",
    description="Chỉ gỡ liên kết, tài khoản giữ nguyên. Người không phải manager thì vẫn trả 204.",
    responses=error_responses(status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def remove_department_manager(
    department_id: IdPath, user_id: IdPath, service: DepartmentServiceDep
) -> None:
    await service.remove_manager(department_id, user_id)
