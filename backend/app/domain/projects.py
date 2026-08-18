"""项目域（SPEC 3.2）：项目 CRUD、成员、职责槽资格（资格与判定分离，D3）。"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.security as security
from app.core.db import get_session
from app.core.errors import ApiError
from app.db_model import Project, ProjectMembership, ProjectRoleGrant, User

router = APIRouter(prefix="/api/v1", tags=["projects"])


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    description: str | None = None


class ProjectOut(BaseModel):
    id: int
    name: str
    code: str
    description: str | None
    my_role: str | None = None


class MemberIn(BaseModel):
    user_id: int | None = None
    role: str
    username: str | None = None  # user_id 与 username 二选一


class GrantIn(BaseModel):
    user_id: int | None = None
    role_slot: str
    username: str | None = None


class Page(BaseModel):
    items: list
    total: int
    page: int
    page_size: int


async def _resolve_user(db: AsyncSession, body) -> int:
    """请求体 user_id 与 username 二选一解析。"""
    if body.user_id:
        return body.user_id
    if body.username:
        uid = (await db.execute(select(User.id).where(User.username == body.username))).scalar_one_or_none()
        if uid is None:
            raise ApiError("E_VALID_REQUEST", f"用户不存在: {body.username}")
        return uid
    raise ApiError("E_VALID_REQUEST", "user_id 与 username 必填其一")


async def require_admin(project_id: int, user: User, db: AsyncSession) -> None:
    """项目管理员校验：创建者角色 'admin' 或成员角色 admin（简化：首个成员即管理员语义）。"""
    role = (
        await db.execute(
            select(ProjectMembership.role).where(
                ProjectMembership.project_id == project_id, ProjectMembership.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if role is None:
        raise ApiError("E_FORBIDDEN_PROJECT", "非项目成员")
    if role != "admin":
        raise ApiError("E_FORBIDDEN_PROJECT", "需要项目管理员权限")


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectIn,
    user: User = Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> ProjectOut:
    """创建项目：创建者自动成为 admin 成员。"""
    # 1. 编码唯一
    dup = (await db.execute(select(Project.id).where(Project.code == body.code))).scalar_one_or_none()
    if dup:
        raise ApiError("E_VALID_REQUEST", f"项目编码已存在: {body.code}")
    # 2. 建项目 + admin 成员
    p = Project(name=body.name, code=body.code, description=body.description)
    db.add(p)
    await db.flush()
    db.add(ProjectMembership(project_id=p.id, user_id=user.id, role="admin"))
    await db.commit()
    return ProjectOut(id=p.id, name=p.name, code=p.code, description=p.description, my_role="admin")


@router.get("/projects")
async def list_projects(
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> Page:
    """当前用户参与的项目列表。"""
    q = (
        select(Project, ProjectMembership.role)
        .join(ProjectMembership, ProjectMembership.project_id == Project.id)
        .where(ProjectMembership.user_id == user.id)
        .order_by(Project.id.desc())
    )
    rows = (await db.execute(q.offset((page - 1) * page_size).limit(page_size))).all()
    total = (
        await db.execute(
            select(func.count())
            .select_from(Project)
            .join(ProjectMembership, ProjectMembership.project_id == Project.id)
            .where(ProjectMembership.user_id == user.id)
        )
    ).scalar_one()
    items = [
        ProjectOut(id=p.id, name=p.name, code=p.code, description=p.description, my_role=role)
        for p, role in rows
    ]
    return Page(items=items, total=total, page=page, page_size=page_size)  # type: ignore[arg-type]


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: int,
    user: User = Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> ProjectOut:
    """项目详情（含当前用户角色）。"""
    p = (
        await db.execute(
            select(Project, ProjectMembership.role)
            .join(ProjectMembership, ProjectMembership.project_id == Project.id)
            .where(Project.id == project_id, ProjectMembership.user_id == user.id)
        )
    ).first()
    if p is None:
        raise ApiError("E_NOT_FOUND", "项目不存在或非成员")
    proj, role = p
    return ProjectOut(id=proj.id, name=proj.name, code=proj.code, description=proj.description, my_role=role)


@router.post("/projects/{project_id}/members", status_code=201)
async def add_member(
    project_id: int,
    body: MemberIn,
    user: User = Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """添加成员（管理员）。role ∈ engineer|approver_data|approver_security|operator|auditor|admin。"""
    await require_admin(project_id, user, db)
    if body.role not in security.MEMBER_ROLES + ("admin",):
        raise ApiError("E_VALID_REQUEST", f"非法角色: {body.role}")
    uid = await _resolve_user(db, body)
    dup = (
        await db.execute(
            select(ProjectMembership.id).where(
                ProjectMembership.project_id == project_id,
                ProjectMembership.user_id == uid,
                ProjectMembership.role == body.role,
            )
        )
    ).scalar_one_or_none()
    if dup is None:
        db.add(ProjectMembership(project_id=project_id, user_id=uid, role=body.role))
        await db.commit()
    return {"ok": True, "user_id": uid, "role": body.role}


@router.get("/projects/{project_id}/members")
async def list_members(
    project_id: int,
    user: User = Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    """成员列表。"""
    await require_admin(project_id, user, db)
    rows = (
        await db.execute(
            select(ProjectMembership, User.username, User.display_name)
            .join(User, User.id == ProjectMembership.user_id)
            .where(ProjectMembership.project_id == project_id)
            .order_by(ProjectMembership.id)
        )
    ).all()
    return [
        {"user_id": m.user_id, "username": uname, "display_name": dname, "role": m.role}
        for m, uname, dname in rows
    ]


@router.post("/projects/{project_id}/role-grants", status_code=201)
async def grant_role(
    project_id: int,
    body: GrantIn,
    user: User = Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """授予职责槽资格（仅资格，不做互斥判定，D3）。"""
    await require_admin(project_id, user, db)
    if body.role_slot not in security.ROLE_SLOTS:
        raise ApiError("E_VALID_REQUEST", f"非法职责槽: {body.role_slot}")
    uid = await _resolve_user(db, body)
    dup = (
        await db.execute(
            select(ProjectRoleGrant.id).where(
                ProjectRoleGrant.project_id == project_id,
                ProjectRoleGrant.user_id == uid,
                ProjectRoleGrant.role_slot == body.role_slot,
            )
        )
    ).scalar_one_or_none()
    if dup is None:
        db.add(ProjectRoleGrant(project_id=project_id, user_id=uid, role_slot=body.role_slot))
        await db.commit()
    return {"ok": True, "user_id": uid, "role_slot": body.role_slot}


@router.get("/projects/{project_id}/role-grants")
async def list_grants(
    project_id: int,
    user: User = Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    """资格列表。"""
    await require_admin(project_id, user, db)
    rows = (
        await db.execute(
            select(ProjectRoleGrant, User.username)
            .join(User, User.id == ProjectRoleGrant.user_id)
            .where(ProjectRoleGrant.project_id == project_id)
            .order_by(ProjectRoleGrant.id)
        )
    ).all()
    return [
        {"user_id": g.user_id, "username": uname, "role_slot": g.role_slot} for g, uname in rows
    ]
