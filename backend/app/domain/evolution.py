"""安全进化域（SPEC 3.12）：改进候选 + 灰度开关（E_EVOLUTION_GATE 准入）。"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.security as security
from app.core.db import get_session
from app.core.errors import ApiError
from app.db_model import BenchmarkRun, EvolutionCandidate, GrayFlag, ProjectMembership

router = APIRouter(prefix="/api/v1/evolution", tags=["evolution"])


async def _require_security_approver(project_id: int, user, db: AsyncSession) -> None:
    """approver_security 角色或 admin。"""
    role = (
        await db.execute(
            select(ProjectMembership.role).where(
                ProjectMembership.project_id == project_id, ProjectMembership.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if role is None:
        raise ApiError("E_FORBIDDEN_PROJECT", "非项目成员")
    if role not in ("approver_security", "admin"):
        raise ApiError("E_FORBIDDEN_PROJECT", "需要 approver_security 角色")


class CandidateIn(BaseModel):
    project_id: int
    kind: str = Field(pattern=r"^(prompt|policy)$")
    title: str = Field(min_length=1, max_length=255)
    content_json: dict


class ReviewIn(BaseModel):
    decision: str = Field(pattern=r"^(approve|reject)$")
    review_report_json: dict


class GrayFlagIn(BaseModel):
    project_id: int
    flag_key: str = Field(min_length=1, max_length=64)
    enabled: bool
    description: str | None = None


def _candidate_out(c: EvolutionCandidate) -> dict:
    return {"id": c.id, "project_id": c.project_id, "kind": c.kind, "title": c.title,
            "content_json": c.content_json, "status": c.status,
            "review_report_json": c.review_report_json, "created_by": c.created_by,
            "created_at": c.created_at, "updated_at": c.updated_at}


@router.get("/candidates")
async def list_candidates(
    project_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """候选列表。"""
    if project_id:
        await _require_security_approver(project_id, user, db)
    q = select(EvolutionCandidate)
    if project_id:
        q = q.where(EvolutionCandidate.project_id == project_id)
    if status:
        q = q.where(EvolutionCandidate.status == status)
    rows = (await db.execute(q.order_by(EvolutionCandidate.id.desc()).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    return {"items": [_candidate_out(c) for c in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/candidates", status_code=201)
async def propose(
    body: CandidateIn,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """提交改进候选。"""
    await _require_security_approver(body.project_id, user, db)
    c = EvolutionCandidate(project_id=body.project_id, kind=body.kind, title=body.title,
                           content_json=body.content_json, created_by=user.id)
    db.add(c)
    await db.commit()
    return _candidate_out(c)


@router.get("/candidates/{candidate_id}")
async def get_candidate(
    candidate_id: int,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    c = (await db.execute(select(EvolutionCandidate).where(EvolutionCandidate.id == candidate_id))).scalar_one_or_none()
    if c is None:
        raise ApiError("E_NOT_FOUND", f"候选不存在: {candidate_id}")
    await _require_security_approver(c.project_id, user, db)
    return _candidate_out(c)


@router.post("/candidates/{candidate_id}/reviews")
async def review(
    candidate_id: int,
    body: ReviewIn,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """评审决策：proposed → approved/rejected。"""
    c = (await db.execute(select(EvolutionCandidate).where(EvolutionCandidate.id == candidate_id))).scalar_one_or_none()
    if c is None:
        raise ApiError("E_NOT_FOUND", f"候选不存在: {candidate_id}")
    await _require_security_approver(c.project_id, user, db)
    if c.status != "proposed":
        raise ApiError("E_VALID_REQUEST", f"候选已评审: {c.status}")
    c.status = "approved" if body.decision == "approve" else "rejected"
    c.review_report_json = body.review_report_json
    await db.commit()
    return _candidate_out(c)


@router.get("/gray-flags")
async def list_flags(
    project_id: int,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    await _require_security_approver(project_id, user, db)
    rows = (await db.execute(select(GrayFlag).where(GrayFlag.project_id == project_id))).scalars().all()
    return [{"project_id": f.project_id, "flag_key": f.flag_key, "enabled": f.enabled,
             "description": f.description, "updated_by": f.updated_by, "updated_at": f.updated_at} for f in rows]


@router.put("/gray-flags")
async def set_flag(
    body: GrayFlagIn,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """更新灰度开关：enabled=true 前置最新成功 benchmark health_score>90。"""
    await _require_security_approver(body.project_id, user, db)
    # 1. 准入检查
    if body.enabled:
        run = (
            await db.execute(
                select(BenchmarkRun)
                .where(BenchmarkRun.status == "succeeded")
                .order_by(BenchmarkRun.id.desc()).limit(1)
            )
        ).scalar_one_or_none()
        score = ((run.metrics_json or {}).get("health_score") if run else None) or 0
        if score <= 90:
            raise ApiError("E_EVOLUTION_GATE", f"最新 benchmark 健康度 {score} ≤ 90，禁止开启灰度")
    # 2. upsert
    flag = (
        await db.execute(
            select(GrayFlag).where(GrayFlag.project_id == body.project_id, GrayFlag.flag_key == body.flag_key)
        )
    ).scalar_one_or_none()
    if flag is None:
        flag = GrayFlag(project_id=body.project_id, flag_key=body.flag_key, updated_by=user.id)
        db.add(flag)
    flag.enabled = body.enabled
    flag.description = body.description
    flag.updated_by = user.id
    flag.updated_at = datetime.now(UTC)
    await db.commit()
    return {"project_id": flag.project_id, "flag_key": flag.flag_key, "enabled": flag.enabled,
            "description": flag.description, "updated_by": flag.updated_by, "updated_at": flag.updated_at}
