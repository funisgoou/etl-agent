"""认证与鉴权（SPEC 2.3）：密码散列、会话令牌、项目边界依赖。

会话语义（R13）：令牌为不透明随机串，库内仅存 SHA256 摘要；鉴权查 sessions 表。
"""

import asyncio
import hashlib
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import ApiError
from app.core.security_util import hash_password_raw, verify_password_hash
from app.db_model import ProjectMembership, ProjectRoleGrant, Session as SessionRow, User

# 成员角色（project_memberships.role）
MEMBER_ROLES = ("engineer", "approver_data", "approver_security", "operator", "auditor")
# 职责槽资格（project_role_grants.role_slot）
ROLE_SLOTS = ("maker", "checker1", "checker2", "operator")


def hash_password(plain: str) -> str:
    """密码散列（pbkdf2，随机盐）。"""
    return hash_password_raw(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """校验密码（线程池执行避免阻塞事件循环）。"""
    return asyncio.get_running_loop().run_in_executor(
        None, verify_password_hash, plain, hashed
    ) if _has_running_loop() else verify_password_hash(plain, hashed)


def _has_running_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def new_session_token() -> str:
    """生成不透明会话令牌本体（仅登录响应中出现一次）。"""
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    """令牌摘要（入库/比对统一口径）。"""
    return hashlib.sha256(token.encode()).hexdigest()


async def current_user(request: Request, db: AsyncSession = Depends(get_session)) -> User:
    """鉴权依赖：Authorization: Bearer <token> → 校验会话未吊销未过期 → 返回用户。

    SSE 场景原生 EventSource 无法携带自定义头，回退读 ?token= 查询参数。
    """
    # 1. 解析令牌（头优先，查询参数兜底——EventSource 专用通道）
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth.removeprefix("Bearer ")
    else:
        token = request.query_params.get("token", "")
    if not token:
        raise ApiError("E_AUTH_UNAUTHORIZED", "缺少会话令牌")
    # 2. 查会话（未吊销 + 未过期）
    row = (
        await db.execute(
            select(User)
            .join(SessionRow, SessionRow.user_id == User.id)
            .where(
                SessionRow.token_digest == token_digest(token),
                SessionRow.revoked_at.is_(None),
                SessionRow.expires_at > datetime.now(UTC),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError("E_AUTH_UNAUTHORIZED", "会话无效或已过期")
    if row.status != "active":
        raise ApiError("E_AUTH_UNAUTHORIZED", "用户已禁用")
    return row


def require_member(project_id: int) -> Callable[..., Awaitable[User]]:
    """依赖工厂：要求当前用户是项目成员。"""

    async def _check(
        user: User = Depends(current_user), db: AsyncSession = Depends(get_session)
    ) -> User:
        mid = (
            await db.execute(
                select(ProjectMembership.id).where(
                    ProjectMembership.project_id == project_id,
                    ProjectMembership.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if mid is None:
            raise ApiError("E_FORBIDDEN_PROJECT", "非项目成员")
        return user

    return _check


def require_member_role(project_id: int, *roles: str) -> Callable[..., Awaitable[User]]:
    """依赖工厂：要求成员角色命中其一（如 engineer）；roles 为空仅要求成员。"""

    async def _check(
        user: User = Depends(current_user), db: AsyncSession = Depends(get_session)
    ) -> User:
        role = (
            await db.execute(
                select(ProjectMembership.role).where(
                    ProjectMembership.project_id == project_id,
                    ProjectMembership.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if role is None:
            raise ApiError("E_FORBIDDEN_PROJECT", "非项目成员")
        if roles and role not in roles:
            raise ApiError("E_FORBIDDEN_PROJECT", f"需要角色: {'/'.join(roles)}")
        return user

    return _check


async def has_role_slot(db: AsyncSession, project_id: int, user_id: int, slot: str) -> bool:
    """查询用户是否持有职责槽资格（互斥判定/依赖工厂共用）。"""
    gid = (
        await db.execute(
            select(ProjectRoleGrant.id).where(
                ProjectRoleGrant.project_id == project_id,
                ProjectRoleGrant.user_id == user_id,
                ProjectRoleGrant.role_slot == slot,
            )
        )
    ).scalar_one_or_none()
    return gid is not None


def require_role_slot(project_id: int, slot: str) -> Callable[..., Awaitable[User]]:
    """依赖工厂：要求职责槽资格（maker/checker1/checker2/operator）。

    D3：资格表仅声明资格，互斥判定发生在 Approve 服务端逻辑。
    """

    async def _check(
        user: User = Depends(current_user), db: AsyncSession = Depends(get_session)
    ) -> User:
        if not await has_role_slot(db, project_id, user.id, slot):
            raise ApiError("E_FORBIDDEN_DUTY", f"缺少 {slot} 职责槽资格")
        return user

    return _check
