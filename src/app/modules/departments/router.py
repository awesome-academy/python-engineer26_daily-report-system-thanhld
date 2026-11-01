from fastapi import APIRouter, status

from app.api.deps import CurrentUser, IdPath
from app.core.exceptions import error_responses
from app.core.pagination import Page, PageQuery
from app.modules.departments.dependencies import (
    DepartmentServiceDep,
    ManagedDepartment,
    ManagedDepartmentForShare,
)
from app.modules.departments.schemas import (
    DepartmentCreate,
    DepartmentDetailOut,
    DepartmentListQuery,
    DepartmentManagerOut,
    DepartmentMemberListQuery,
    DepartmentMemberOut,
    DepartmentOut,
    DepartmentUpdate,
    ManagerAssign,
    MemberCandidateListQuery,
    MemberCandidateOut,
    MembersAdd,
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
    description=(
        "Thành viên là user thuộc bộ phận, sắp theo họ tên (không phân biệt hoa thường, không "
        "dấu), kèm `is_manager` để chọn người gán manager."
    ),
    responses=error_responses(status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def list_department_members(
    department_id: IdPath, params: PageQuery, service: DepartmentServiceDep
) -> Page[DepartmentMemberOut]:
    return await service.list_members(department_id, params)


@admin_department_router.get(
    "/{department_id}/managers",
    summary="Xem manager của bộ phận",
    description=(
        "Manager không cần là thành viên bộ phận nên có thể không hiện ở `/members`; xem ở đây để "
        "gỡ. Sắp theo họ tên (không phân biệt hoa thường, không dấu)."
    ),
    responses=error_responses(status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def list_department_managers(
    department_id: IdPath, params: PageQuery, service: DepartmentServiceDep
) -> Page[DepartmentManagerOut]:
    return await service.list_managers(department_id, params)


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
    description=(
        "Chỉ gỡ liên kết, tài khoản giữ nguyên. Người không phải manager của bộ phận thì vẫn trả "
        "204; user không tồn tại hoặc đã xóa thì 404."
    ),
    responses=error_responses(status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def remove_department_manager(
    department_id: IdPath, user_id: IdPath, service: DepartmentServiceDep
) -> None:
    await service.remove_manager(department_id, user_id)


# Include vào nhóm /manager (api/v1.py): role MANAGER được kiểm tra ở nhóm, 401, 403 khai ở nhóm.
# Endpoint có {department_id} nhận bộ phận qua ManagedDepartment: ngoài phạm vi trả 404. Endpoint
# ghi dùng ManagedDepartmentForShare: khóa bộ phận tới hết transaction, admin không xóa xen được.
manager_department_router = APIRouter(prefix="/departments", tags=["Manager: bộ phận"])


@manager_department_router.get(
    "",
    summary="Bộ phận tôi quản lý",
    description=(
        "Các bộ phận admin đã gán cho tôi làm manager. Tìm theo mã hoặc tên (không phân biệt "
        "hoa thường, không dấu), sắp theo mã."
    ),
    responses=error_responses(status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def list_my_departments(
    params: DepartmentListQuery, manager: CurrentUser, service: DepartmentServiceDep
) -> Page[DepartmentOut]:
    departments, total = await service.list_managed_departments(manager.id, params)
    return Page[DepartmentOut].build(
        [DepartmentOut.model_validate(department) for department in departments],
        total=total,
        params=params,
    )


@manager_department_router.get(
    "/{department_id}",
    summary="Xem bộ phận tôi quản lý",
    description="Kèm các manager của bộ phận (sắp theo họ tên) và số thành viên.",
    responses=error_responses(status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def get_my_department(
    department: ManagedDepartment, service: DepartmentServiceDep
) -> DepartmentDetailOut:
    return await service.get_department_detail(department)


@manager_department_router.get(
    "/{department_id}/members",
    summary="Thành viên bộ phận tôi quản lý",
    description=(
        "Tìm theo họ tên (không dấu) hoặc email, sắp theo họ tên (không phân biệt hoa thường, "
        "không dấu). Gồm cả tài khoản bị khóa, kèm `is_manager`."
    ),
    responses=error_responses(status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def list_my_department_members(
    department: ManagedDepartment,
    params: DepartmentMemberListQuery,
    service: DepartmentServiceDep,
) -> Page[DepartmentMemberOut]:
    return await service.list_managed_members(department, params)


@manager_department_router.post(
    "/{department_id}/members",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Thêm nhân viên vào bộ phận",
    description=(
        "Mỗi id phải là ứng viên (GET /manager/candidates) hoặc đã là thành viên bộ phận này: "
        "gửi lại không lỗi. Còn id sai thì không thêm ai, trả 422 `INVALID_MEMBER_CANDIDATE` "
        "kèm `invalid_ids`."
    ),
    responses=error_responses(status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def add_department_members(
    department: ManagedDepartmentForShare, data: MembersAdd, service: DepartmentServiceDep
) -> None:
    await service.add_members(department.id, data.user_ids)


@manager_department_router.delete(
    "/{department_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Gỡ nhân viên khỏi bộ phận",
    description=(
        "Chỉ gỡ liên kết, tài khoản giữ nguyên. Người không thuộc bộ phận này thì vẫn trả 204; "
        "user không tồn tại hoặc đã xóa thì 404. Thành viên role khác USER do admin xếp bộ phận: "
        "422 `EMPLOYEE_ROLE_REQUIRED`."
    ),
    responses=error_responses(status.HTTP_404_NOT_FOUND, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def remove_department_member(
    department: ManagedDepartmentForShare, user_id: IdPath, service: DepartmentServiceDep
) -> None:
    await service.remove_member(department.id, user_id)


# Ứng viên chưa thuộc bộ phận nào nên không nằm dưới /departments/{department_id}.
manager_candidate_router = APIRouter(prefix="/candidates", tags=["Manager: bộ phận"])


@manager_candidate_router.get(
    "",
    summary="Ứng viên thêm vào bộ phận",
    description=(
        "Nhân viên role USER đang hoạt động, chưa thuộc bộ phận nào. Tìm theo họ tên (không phân "
        "biệt hoa thường, không dấu) hoặc email, sắp theo họ tên."
    ),
    responses=error_responses(status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def list_member_candidates(
    params: MemberCandidateListQuery, service: DepartmentServiceDep
) -> Page[MemberCandidateOut]:
    users, total = await service.list_candidates(params)
    return Page[MemberCandidateOut].build(
        [MemberCandidateOut.model_validate(user) for user in users], total=total, params=params
    )
