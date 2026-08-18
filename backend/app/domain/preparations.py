"""准备单域（SPEC 3.8）：Prepare / Approve / Commit 三阶段协议编排。

核心不变式：
- Prepare：指纹推导 + 预算冻结 + PDP 评级 + 双审批单 + 账本（无外部副作用）。
- Approve：职责槽资格 + 禁止自批 + 槽间互斥（D3，服务端强制）。
- Commit：审批齐 + 未过期 + 指纹重算比对 + 单事务（状态/ExecutionRun/Outbox/Capability）。
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.security as security
from app.core.config import get_settings
from app.core.db import atomic, get_session
from app.core.errors import ApiError
from app.db_model import (ApprovalRequest, Connection, ExecutionRun, Pipeline,
                          PipelineVersion, Preparation)
from app.harness import capability, outbox
from app.harness.intents import ToolIntent
from app.harness.ledger import append
from app.harness.pdp import evaluate

router = APIRouter(prefix="/api/v1", tags=["preparations"])
logger = structlog.get_logger(__name__)


class DecideIn(BaseModel):
    decision: str  # approve | reject
    comment: str | None = None


def compute_fingerprint(version: PipelineVersion, plan: dict) -> str:
    """输入指纹 = SHA256(制品 + 连接引用 + 目标表)（canonical JSON）。"""
    payload = {
        "version_id": version.id,
        "artifact_digest": version.artifact_digest,
        "etl_plan": plan,
        "hocon": version.hocon_text,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


async def _version_and_project(db: AsyncSession, version_id: int) -> tuple[PipelineVersion, int]:
    v = (await db.execute(select(PipelineVersion).where(PipelineVersion.id == version_id))).scalar_one_or_none()
    if v is None:
        raise ApiError("E_NOT_FOUND", f"版本不存在: {version_id}")
    p = (await db.execute(select(Pipeline).where(Pipeline.id == v.pipeline_id))).scalar_one()
    return v, p.project_id


async def _plan_facts(db: AsyncSession, plan: dict) -> dict:
    """从 EtlPlan 提取资源范围/影响/分级（确定性推导）。"""
    source = plan.get("source", {})
    target = plan.get("target", {})
    scope_src = []
    if source.get("kind") == "mysql" and source.get("table"):
        conn = (await db.execute(select(Connection).where(Connection.id == source.get("connection_id")))).scalar_one_or_none()
        db_name = (conn.config_json or {}).get("database", "?") if conn else "?"
        scope_src.append(f"mysql:{db_name}.{source['table']}")
    elif source.get("file_asset_id"):
        scope_src.append(f"csv:file_asset_{source['file_asset_id']}")
    return {
        "resource_scope": {"source": scope_src, "target": [f"doris:{target.get('table')}"]},
        "impact": {"write_tables": [f"{target.get('table')}__raw", f"{target.get('table')}__shadow",
                                    f"{target.get('table')}__err", target.get('table')]},
        "classification": plan.get("data_classification", "internal"),
    }


@router.post("/versions/{version_id}/prepare", status_code=201)
async def prepare(
    version_id: int,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """生成准备单：冻结事实 + PDP 评级 + 双审批单 + 账本。"""
    # 1. 前置：版本已冻结 + maker 资格 + 无未终结准备单
    v, project_id = await _version_and_project(db, version_id)
    if not await security.has_role_slot(db, project_id, user.id, "maker"):
        raise ApiError("E_FORBIDDEN_DUTY", "需要 maker 职责槽资格")
    if not v.is_immutable:
        raise ApiError("E_VALID_REQUEST", "版本未冻结，不能发起审批")
    active = (
        await db.execute(
            select(Preparation.id).where(
                Preparation.version_id == version_id,
                Preparation.status.in_(("pending", "approved", "committed")),
            )
        )
    ).scalar_one_or_none()
    if active:
        raise ApiError("E_VALID_REQUEST", f"已存在未终结准备单: {active}")
    # 2. 推导冻结事实
    plan = v.etl_plan_json or {}
    facts = await _plan_facts(db, plan)
    fingerprint = compute_fingerprint(v, plan)
    budget = {"max_read_rows": 1_000_000, "max_write_bytes": 2 * 1024**3, "max_duration_seconds": 1800}
    rollback = {"steps": ["restore_from___bak", "drop___shadow", "truncate___raw"], "mechanism": "swap 回滚（P1 受管）"}
    # 3. PDP 评级
    intent = ToolIntent(
        tool="execute_pipeline", version_id=version_id, project_id=project_id,
        subject_id=user.id, resource_scope=facts["resource_scope"],
        data_classification=facts["classification"], params={},
    )
    decision = evaluate(intent)
    if decision.risk_level == "P0":
        raise ApiError("E_VALID_REQUEST", "PDP 评级 P0：secret 分级数据禁止执行")
    # 4. 落库（独立事务提交——纪律 #6：prepare 写完即提交，避免 decide 404）
    async with atomic() as tx:
        prep = Preparation(
            version_id=version_id,
            maker_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=get_settings().preparation_ttl_hours),
            input_fingerprint=fingerprint,
            resource_scope=facts["resource_scope"],
            impact_json=facts["impact"],
            data_classification=facts["classification"],
            budget_json=budget,
            rollback_plan_json=rollback,
            risk_level=decision.risk_level,
            status="pending",
        )
        tx.add(prep)
        await tx.flush()
        reqs = [
            ApprovalRequest(preparation_id=prep.id, version_id=version_id, required_role=slot, status="pending")
            for slot in decision.requires
        ]
        tx.add_all(reqs)
        evt = await append(tx, project_id, user.id, "prepare", "preparation", prep.id,
                           {"fingerprint": fingerprint, "risk_level": decision.risk_level})
        await tx.commit()
    return {
        "id": prep.id, "version_id": version_id, "status": "pending", "maker_id": user.id,
        "expires_at": prep.expires_at, "input_fingerprint": fingerprint,
        "resource_scope": facts["resource_scope"], "impact_json": facts["impact"],
        "data_classification": facts["classification"], "budget_json": budget,
        "rollback_plan_json": rollback, "risk_level": decision.risk_level,
        "approval_requests": [{"id": r.id, "required_role": r.required_role, "status": "pending"} for r in reqs],
        "audit_event_id": evt.id,
    }


@router.post("/approval-requests/{approval_id}/decisions")
async def decide(
    approval_id: int,
    body: DecideIn,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """具名审批：资格 + 自批禁令 + 槽间互斥（D3）。"""
    if body.decision not in ("approve", "reject"):
        raise ApiError("E_VALID_REQUEST", "decision 必须为 approve|reject")
    ar = (await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == approval_id))).scalar_one_or_none()
    if ar is None:
        raise ApiError("E_NOT_FOUND", f"审批单不存在: {approval_id}")
    prep = (await db.execute(select(Preparation).where(Preparation.id == ar.preparation_id))).scalar_one()
    _, project_id = await _version_and_project(db, prep.version_id)
    if ar.status != "pending" or prep.status not in ("pending", "approved"):
        raise ApiError("E_PREP_INVALID_STATE", f"准备单已终结: {prep.status}")
    # 1. 职责槽资格
    if not await security.has_role_slot(db, project_id, user.id, ar.required_role):
        raise ApiError("E_FORBIDDEN_DUTY", f"缺少 {ar.required_role} 职责槽资格",
                       details={"preparation_id": prep.id, "conflict_slot": ar.required_role})
    # 2. 禁止自批（Maker ≠ 审批人）
    if prep.maker_id == user.id:
        raise ApiError("E_FORBIDDEN_DUTY", "申请人禁止自批",
                       details={"preparation_id": prep.id, "conflict_slot": ar.required_role})
    # 3. 槽间互斥：另一职责槽已被同一人占用则拒绝
    others = (
        await db.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.preparation_id == prep.id,
                ApprovalRequest.id != ar.id,
                ApprovalRequest.approver_id.is_not(None),
            )
        )
    ).scalars().all()
    for o in others:
        if o.approver_id == user.id:
            raise ApiError("E_FORBIDDEN_DUTY", "同一 Preparation 单内同一用户只能占用一个职责槽",
                           details={"preparation_id": prep.id, "conflict_slot": o.required_role})
    # 4. 决策落库 + 联动状态 + 账本
    async with atomic() as tx:
        ar_tx = await tx.get(ApprovalRequest, approval_id)
        ar_tx.status = "decided"
        ar_tx.decision = body.decision
        ar_tx.approver_id = user.id
        ar_tx.decided_at = datetime.now(UTC)
        if body.decision == "reject":
            prep_tx = await tx.get(Preparation, prep.id)
            prep_tx.status = "rejected"
            # 余下审批单作废
            for o in await tx.execute(
                select(ApprovalRequest).where(
                    ApprovalRequest.preparation_id == prep.id, ApprovalRequest.status == "pending"
                )
            ).scalars():
                o.status = "cancelled"
        else:
            # 全部 decided 且 approve → approved
            all_reqs = (await tx.execute(
                select(ApprovalRequest).where(ApprovalRequest.preparation_id == prep.id)
            )).scalars().all()
            if all(r.decision == "approve" for r in all_reqs):
                prep_tx = await tx.get(Preparation, prep.id)
                prep_tx.status = "approved"
        evt = await append(tx, project_id, user.id, "approve" if body.decision == "approve" else "reject",
                           "approval_request", approval_id, {"decision": body.decision, "comment": body.comment})
        await tx.commit()
    return {"id": ar.id, "status": "decided", "decision": body.decision,
            "approver_id": user.id, "decided_at": ar.decided_at, "audit_event_id": evt.id}


@router.post("/preparations/{preparation_id}/commit", status_code=201)
async def commit(
    preparation_id: int,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Commit：校验审批/过期/指纹 → 签发 Capability → 单事务原子提交。"""
    # 1. operator 资格
    prep = (await db.execute(select(Preparation).where(Preparation.id == preparation_id))).scalar_one_or_none()
    if prep is None:
        raise ApiError("E_NOT_FOUND", f"准备单不存在: {preparation_id}")
    v, project_id = await _version_and_project(db, prep.version_id)
    if not await security.has_role_slot(db, project_id, user.id, "operator"):
        raise ApiError("E_FORBIDDEN_DUTY", "需要 operator 职责槽资格")
    # 2. 审批齐 + 未过期
    if prep.status != "approved":
        raise ApiError("E_PREP_NOT_APPROVED", f"准备单状态 {prep.status}，不可提交执行")
    if prep.expires_at < datetime.now(UTC):
        raise ApiError("E_PREP_EXPIRED", "准备单已过期")
    # 3. 指纹重算比对（制品被替换 → 拒绝）
    fingerprint = compute_fingerprint(v, v.etl_plan_json or {})
    if fingerprint != prep.input_fingerprint:
        raise ApiError("E_FINGERPRINT_MISMATCH", "输入指纹与准备单不一致，制品已被替换，需重新 Prepare")
    # 4. 单事务：状态迁移 + Capability + ExecutionRun + Outbox + 账本
    async with atomic() as tx:
        token = await capability.issue(tx, "execute_pipeline", user.id, v.artifact_digest)
        prep_tx = await tx.get(Preparation, preparation_id)
        prep_tx.status = "committed"
        run = ExecutionRun(
            version_id=v.id, preparation_id=preparation_id, run_kind="execute",
            capability_token_digest=hashlib.sha256(token.encode()).hexdigest(),
            status="pending", row_count_check="pending",
            source_row_count=(v.etl_plan_json or {}).get("_source_row_hint"),
        )
        tx.add(run)
        await tx.flush()
        await outbox.emit(
            tx, "execution_run", run.id, "execute_pipeline",
            {"execution_run_id": run.id, "version_id": v.id, "token": token,
             "project_id": project_id, "operator_id": user.id},
        )
        evt = await append(tx, project_id, user.id, "commit", "execution_run", run.id,
                           {"preparation_id": preparation_id, "fingerprint": fingerprint})
        await tx.commit()
    logger.info("commit 成功", run_id=run.id, preparation_id=preparation_id)
    return {"execution_run_id": run.id, "status": "pending", "capability_issued": True, "audit_event_id": evt.id}


@router.get("/preparations/{preparation_id}")
async def get_preparation(
    preparation_id: int,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """准备单详情（含审批状态与展示字段）。"""
    prep = (await db.execute(select(Preparation).where(Preparation.id == preparation_id))).scalar_one_or_none()
    if prep is None:
        raise ApiError("E_NOT_FOUND", f"准备单不存在: {preparation_id}")
    v, project_id = await _version_and_project(db, prep.version_id)
    await security.require_member(project_id)(user, db)
    from app.db_model import User

    maker = (await db.execute(select(User).where(User.id == prep.maker_id))).scalar_one_or_none()
    reqs = (await db.execute(
        select(ApprovalRequest).where(ApprovalRequest.preparation_id == preparation_id)
    )).scalars().all()
    return {
        "id": prep.id, "code": f"PR-{prep.id:03d}", "version_id": prep.version_id,
        "pipeline_id": v.pipeline_id, "maker_id": prep.maker_id,
        "maker_name": maker.display_name if maker else None,
        "status": prep.status, "expires_at": prep.expires_at,
        "input_fingerprint": prep.input_fingerprint, "resource_scope": prep.resource_scope,
        "impact_json": prep.impact_json, "data_classification": prep.data_classification,
        "budget_json": prep.budget_json, "rollback_plan_json": prep.rollback_plan_json,
        "risk_level": prep.risk_level, "created_at": prep.created_at,
        "approval_requests": [
            {"id": r.id, "required_role": r.required_role, "status": r.status,
             "decision": r.decision, "approver_id": r.approver_id, "decided_at": r.decided_at}
            for r in reqs
        ],
    }


@router.get("/projects/{project_id}/preparations")
async def list_preparations(
    project_id: int,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """项目准备单列表（前端运行中心/审批视图）。"""
    from app.db_model import PipelineVersion

    await security.require_member(project_id)(user, db)
    pipe_ids = select(Pipeline.id).where(Pipeline.project_id == project_id)
    q = select(Preparation).where(
        Preparation.version_id.in_(select(PipelineVersion.id).where(PipelineVersion.pipeline_id.in_(pipe_ids)))
    )
    if status:
        q = q.where(Preparation.status == status)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await db.execute(q.order_by(Preparation.id.desc()).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    items = []
    for prep in rows:
        reqs = (await db.execute(
            select(ApprovalRequest).where(ApprovalRequest.preparation_id == prep.id)
        )).scalars().all()
        items.append({
            "id": prep.id, "code": f"PR-{prep.id:03d}", "version_id": prep.version_id,
            "maker_id": prep.maker_id, "status": prep.status, "expires_at": prep.expires_at,
            "risk_level": prep.risk_level, "data_classification": prep.data_classification,
            "created_at": prep.created_at,
            "approval_requests": [
                {"id": r.id, "required_role": r.required_role, "status": r.status,
                 "decision": r.decision, "approver_id": r.approver_id, "decided_at": r.decided_at}
                for r in reqs
            ],
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}
