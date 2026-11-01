"""Manager thêm, gỡ nhân viên (M2): nhả khóa khi lỗi, chạy song song với thao tác khác."""

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.constants import BIGINT_MAX
from app.core.exceptions import AppError
from app.modules.departments.exceptions import (
    DepartmentNotEmptyError,
    EmployeeRoleRequiredError,
    InvalidMemberCandidateError,
)
from app.modules.departments.service import DepartmentService
from app.modules.users.exceptions import UserNotFoundError
from app.modules.users.models import User, UserRole
from tests.factories import create_department, create_user
from tests.helpers import LOCK_WAIT_SECONDS


async def _add_invalid(service: DepartmentService, department_id: int) -> None:
    await service.add_members(department_id, [BIGINT_MAX])


async def _remove_missing(service: DepartmentService, department_id: int) -> None:
    await service.remove_member(department_id, BIGINT_MAX)


@pytest.mark.parametrize(
    ("action", "error"),
    [
        (_add_invalid, InvalidMemberCandidateError),
        (_remove_missing, UserNotFoundError),
    ],
    ids=["add-invalid", "remove-missing"],
)
async def test_member_change_releases_locks_before_raising(
    db_session: AsyncSession,
    action: Callable[[DepartmentService, int], Awaitable[None]],
    error: type[AppError],
) -> None:
    department = await create_department(db_session)

    with pytest.raises(error):
        await action(DepartmentService(db_session), department.id)

    assert not db_session.in_transaction()


async def test_remove_member_with_other_role_releases_locks(db_session: AsyncSession) -> None:
    department = await create_department(db_session)
    member = await create_user(db_session, role=UserRole.MANAGER, department=department)

    with pytest.raises(EmployeeRoleRequiredError):
        await DepartmentService(db_session).remove_member(department.id, member.id)

    assert not db_session.in_transaction()


async def test_removing_non_member_releases_locks(db_session: AsyncSession) -> None:
    department = await create_department(db_session)
    user = await create_user(db_session)

    await DepartmentService(db_session).remove_member(department.id, user.id)

    assert not db_session.in_transaction()


@dataclass(frozen=True)
class Scene:
    manager_id: int
    department_id: int
    other_department_id: int
    user_id: int


async def _setup(engine: AsyncEngine, *, member: bool = False) -> Scene:
    """Bộ phận của manager, một bộ phận khác, một nhân viên (thành viên bộ phận nếu `member`)."""
    async with AsyncSession(engine) as setup:
        manager = await create_user(setup, role=UserRole.MANAGER)
        department = await create_department(setup, managers=[manager])
        other = await create_department(setup)
        user = await create_user(setup, department=department if member else None)
        scene = Scene(manager.id, department.id, other.id, user.id)
        await setup.commit()
    return scene


async def _department_of(engine: AsyncEngine, user_id: int) -> int | None:
    async with AsyncSession(engine) as session:
        return await session.scalar(select(User.department_id).where(User.id == user_id))


async def _move_user_while(
    engine: AsyncEngine, scene: Scene, action: Callable[[AsyncSession], Coroutine[Any, Any, None]]
) -> AppError | None:
    """Chạy `action` trong lúc transaction khác đang chuyển user sang bộ phận khác, chưa commit.

    Transaction kia là manager bộ phận khác thêm cùng người đó, hoặc admin đổi bộ phận của user.
    """
    async with AsyncSession(engine) as other, AsyncSession(engine) as session:
        await other.execute(select(User).where(User.id == scene.user_id).with_for_update())
        await other.execute(
            update(User)
            .where(User.id == scene.user_id)
            .values(department_id=scene.other_department_id)
        )
        task = asyncio.create_task(action(session))
        # Có khóa thì action phải chờ; không có thì nó đọc bản cũ rồi ghi đè sau khi kia commit.
        await asyncio.sleep(LOCK_WAIT_SECONDS)
        await other.commit()
        try:
            await task
        except AppError as error:
            return error
        return None


@pytest.mark.usefixtures("clean_after")
async def test_two_managers_cannot_both_add_the_same_candidate(engine: AsyncEngine) -> None:
    scene = await _setup(engine)

    async def add(session: AsyncSession) -> None:
        await DepartmentService(session).add_members(scene.department_id, [scene.user_id])

    result = await _move_user_while(engine, scene, add)

    assert isinstance(result, InvalidMemberCandidateError)
    assert await _department_of(engine, scene.user_id) == scene.other_department_id


@pytest.mark.usefixtures("clean_after")
async def test_remove_member_keeps_user_moved_by_admin_meanwhile(engine: AsyncEngine) -> None:
    # Không khóa dòng user thì lệnh gỡ đọc bộ phận cũ, rồi ghi null đè lên bộ phận admin vừa đổi.
    scene = await _setup(engine, member=True)

    async def remove(session: AsyncSession) -> None:
        await DepartmentService(session).remove_member(scene.department_id, scene.user_id)

    result = await _move_user_while(engine, scene, remove)

    assert result is None
    assert await _department_of(engine, scene.user_id) == scene.other_department_id


@pytest.mark.usefixtures("clean_after")
async def test_delete_department_waits_for_members_being_added(engine: AsyncEngine) -> None:
    # Không khóa FOR SHARE thì admin xóa xong bộ phận (lúc đó chưa có thành viên) trong khi manager
    # đang thêm, nhân viên bị xếp vào bộ phận đã xóa.
    scene = await _setup(engine)

    async def delete_department() -> None:
        async with AsyncSession(engine) as session:
            await DepartmentService(session).delete_department(scene.department_id)

    async with AsyncSession(engine) as session:
        service = DepartmentService(session)
        # Như ManagedDepartmentForShare chạy trước handler, trong cùng session.
        await service.get_managed_department(scene.manager_id, scene.department_id, for_share=True)
        deletion = asyncio.create_task(delete_department())
        await asyncio.wait({deletion}, timeout=LOCK_WAIT_SECONDS)
        await service.add_members(scene.department_id, [scene.user_id])

    with pytest.raises(DepartmentNotEmptyError):
        await deletion
    assert await _department_of(engine, scene.user_id) == scene.department_id
