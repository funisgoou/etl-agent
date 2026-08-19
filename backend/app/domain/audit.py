"""审计域（SPEC 3.11 / D9）：事件只读视图 + 账本哈希链校验。"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.security as security
from app.core.db import get_session
from app.core.errors import ApiError
from app.db_model import AuditEvent
from app.harness.ledger import verify_ledger

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


async def _require_auditor(project_id: int, user, db: AsyncSession) -> None:
    """审计权限：auditor 角色或 admin。"""
    from app.db_model import ProjectMembership

    role = (
        await db.execute(
            select(ProjectMembership.role).where(
                ProjectMembership.project_id == project_id, ProjectMembership.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if role is None:
        raise ApiError("E_FORBIDDEN_PROJECT", "非项目成员")
    if role not in ("auditor", "admin"):
        raise ApiError("E_FORBIDDEN_PROJECT", "需要 auditor 角色")


# 事件类型 → 中文摘要（前端审计列表 summary 列）
_EVENT_LABELS = {
    "prepare": "生成准备单（冻结指纹/预算/回滚方案）",
    "approve": "审批通过", "reject": "审批驳回",
    "commit": "提交执行（签发 Capability）",
    "dry_run": "受管试运行", "cancel": "取消运行",
    "rollback": "受管回滚", "rerun": "安全重跑",
    "prepare_expired": "准备单过期",
    "execute_pipeline_executed": "执行完成", "execute_pipeline_failed": "执行失败",
}


@router.get("/events")
async def list_events(
    project_id: int,
    event_type: str | None = None,
    actor_id: int | None = None,
    keyword: str | None = None,
    from_: str | None = None,
    to: str | None = None,
    page: int = 1,
    page_size: int = 20,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """审计事件列表（keyword 演示过滤：匹配事件类型/摘要）。"""
    await _require_auditor(project_id, user, db)
    q = select(AuditEvent).where(AuditEvent.project_id == project_id)
    if event_type:
        q = q.where(AuditEvent.event_type == event_type)
    if actor_id:
        q = q.where(AuditEvent.actor_id == actor_id)
    if from_:
        q = q.where(AuditEvent.created_at >= from_)
    if to:
        q = q.where(AuditEvent.created_at <= to)
    if keyword:
        q = q.where(AuditEvent.event_type.ilike(f"%{keyword}%"))
    rows = (await db.execute(q.order_by(AuditEvent.id.desc()).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    # 操作人名字联查（审计列表展示用；id 集中去查，避免 N+1）
    from app.db_model import User

    actor_ids = {r.actor_id for r in rows}
    name_map: dict[int, str] = {}
    if actor_ids:
        for uid, dname in (
            await db.execute(select(User.id, User.display_name).where(User.id.in_(actor_ids)))
        ).all():
            name_map[uid] = dname
    return {
        "items": [
            {"id": r.id, "project_id": r.project_id, "actor_id": r.actor_id,
             "actor_name": name_map.get(r.actor_id), "event_type": r.event_type,
             "resource_type": r.resource_type, "resource_id": str(r.resource_id),
             "summary": _EVENT_LABELS.get(r.event_type, r.event_type),
             "payload_json": r.payload_json,
             "prev_event_hash": r.prev_event_hash, "event_hash": r.event_hash, "created_at": r.created_at}
            for r in rows
        ],
        "total": total, "page": page, "page_size": page_size,
    }


@router.get("/verify")
async def verify(
    project_id: int,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """重算哈希链并报告断点（D9 篡改演示验收入口）。"""
    await _require_auditor(project_id, user, db)
    return await verify_ledger(db, project_id)
