"""认证域（SPEC 3.1）：注册/登录/注销 + 会话管理。

不变式：密码仅存散列；登录失败不区分原因；令牌只存摘要。
"""

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.security as security
from app.core.db import get_session
from app.core.errors import ApiError
from app.db_model import Session as SessionRow
from app.db_model import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

SESSION_TTL_DAYS = 7


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    email: str | None = None


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    email: str | None
    status: str
    # 前端演示字段：全部项目成员角色与职责槽资格
    roles: list[str] = []
    role_slots: list[str] = []


class LoginOut(BaseModel):
    token: str
    expires_at: datetime
    user: UserOut


def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, username=u.username, display_name=u.display_name, email=u.email, status=u.status)


@router.post("/register", response_model=UserOut, status_code=201)
async def register(body: RegisterIn, db: AsyncSession = Depends(get_session)) -> UserOut:
    """注册：用户名唯一。"""
    # 1. 查重
    exists = (
        await db.execute(select(User.id).where(User.username == body.username))
    ).scalar_one_or_none()
    if exists:
        raise ApiError("E_VALID_USERNAME_TAKEN", "用户名已存在")
    # 2. 落库
    u = User(
        username=body.username,
        display_name=body.display_name,
        email=body.email,
        password_hash=security.hash_password(body.password),
    )
    db.add(u)
    await db.commit()
    return _user_out(u)


@router.post("/login", response_model=LoginOut)
async def login(body: LoginIn, db: AsyncSession = Depends(get_session)) -> LoginOut:
    """登录：签发不透明令牌，sessions 表只存摘要。"""
    # 1. 取用户 + 校验密码（失败统一口径）
    u = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if u is None or u.status != "active" or not security.verify_password(body.password, u.password_hash):
        raise ApiError("E_AUTH_INVALID_CREDENTIALS", "用户名或密码错误")
    # 2. 聚合角色（前端 User.roles/role_slots：全部项目成员角色与职责槽资格）
    from app.db_model import ProjectMembership, ProjectRoleGrant

    roles = (
        await db.execute(
            select(ProjectMembership.role).where(ProjectMembership.user_id == u.id)
        )
    ).scalars().all()
    role_slots = (
        await db.execute(
            select(ProjectRoleGrant.role_slot).where(ProjectRoleGrant.user_id == u.id)
        )
    ).scalars().all()
    # 3. 写会话
    token = security.new_session_token()
    expires = datetime.now(UTC) + timedelta(days=SESSION_TTL_DAYS)
    db.add(SessionRow(token_digest=security.token_digest(token), user_id=u.id, expires_at=expires))
    await db.commit()
    out = _user_out(u)
    out.roles = sorted(set(roles))
    out.role_slots = sorted(set(role_slots))
    return LoginOut(token=token, expires_at=expires, user=out)


@router.post("/logout", status_code=204)
async def logout(request: Request, db: AsyncSession = Depends(get_session)) -> None:
    """注销：Authorization 摘要 → 置位 revoked_at。"""
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    row = (
        await db.execute(
            select(SessionRow).where(SessionRow.token_digest == security.token_digest(token))
        )
    ).scalar_one_or_none()
    if row is not None:
        row.revoked_at = datetime.now(UTC)
    await db.commit()
