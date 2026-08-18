"""执行运行域（SPEC 3.9）：查询、SSE 推送、Dry-Run、取消/回滚/重跑（全部经 Harness）。"""

import asyncio
import hashlib
import json
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.security as security
from app.core import redis_client
from app.core.db import atomic, get_session
from app.core.errors import ApiError
from app.db_model import ExecutionRun, Pipeline, PipelineVersion, Preparation
from app.domain.preparations import _version_and_project, compute_fingerprint
from app.harness import capability, outbox
from app.harness.intents import ToolIntent
from app.harness.ledger import append
from app.harness.pdp import evaluate

router = APIRouter(prefix="/api/v1", tags=["executions"])
logger = structlog.get_logger(__name__)

TERMINAL = ("succeeded", "failed", "cancelled", "rolled_back")


async def _run_and_project(db: AsyncSession, run_id: int) -> tuple[ExecutionRun, int]:
    run = (await db.execute(select(ExecutionRun).where(ExecutionRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise ApiError("E_NOT_FOUND", f"执行不存在: {run_id}")
    v = (await db.execute(select(PipelineVersion).where(PipelineVersion.id == run.version_id))).scalar_one()
    p = (await db.execute(select(Pipeline).where(Pipeline.id == v.pipeline_id))).scalar_one()
    return run, p.project_id


def _run_out(run: ExecutionRun) -> dict:
    return {
        "id": run.id, "version_id": run.version_id, "preparation_id": run.preparation_id,
        "run_kind": run.run_kind, "status": run.status, "sub_stage": run.sub_stage,
        "engine_job_id": run.engine_job_id,
        "input_records": run.input_records, "output_records": run.output_records,
        "error_records": run.error_records, "bytes_processed": run.bytes_processed,
        "row_count_check": run.row_count_check,
        "diagnosis": run.diagnosis_json,
        "quality_report": (run.diagnosis_json or {}).get("quality_report"),
        "started_at": run.started_at, "finished_at": run.finished_at,
        "created_at": run.created_at,
    }


@router.get("/execution-runs/{run_id}")
async def get_run(
    run_id: int, user=Depends(security.current_user), db: AsyncSession = Depends(get_session)
) -> dict:
    """执行状态 + 指标 + 质量报告。"""
    run, project_id = await _run_and_project(db, run_id)
    await security.require_member(project_id)(user, db)
    return _run_out(run)


@router.get("/projects/{project_id}/execution-runs")
async def list_runs(
    project_id: int,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """项目执行列表。"""
    await security.require_member(project_id)(user, db)
    pipe_ids = select(Pipeline.id).where(Pipeline.project_id == project_id)
    ver_ids = select(PipelineVersion.id).where(PipelineVersion.pipeline_id.in_(pipe_ids))
    q = select(ExecutionRun).where(ExecutionRun.version_id.in_(ver_ids))
    if status:
        q = q.where(ExecutionRun.status == status)
    rows = (await db.execute(q.order_by(ExecutionRun.id.desc()).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    return {"items": [_run_out(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/execution-runs/{run_id}/stream")
async def stream_run(
    run_id: int, user=Depends(security.current_user), db: AsyncSession = Depends(get_session)
) -> StreamingResponse:
    """SSE 实时状态（D7）：订阅 exec_run:{id}，先推快照再订阅，终态即关流。"""
    run, project_id = await _run_and_project(db, run_id)
    await security.require_member(project_id)(user, db)
    channel = f"exec_run:{run_id}"

    async def gen():
        # 1. 快照先行（断线重连兜底：事件先落库，这里读库即最新事实）
        yield f"event: status\ndata: {json.dumps(_run_out(run), ensure_ascii=False, default=str)}\n\n"
        if run.status in TERMINAL:
            yield f"event: done\ndata: {json.dumps({'status': run.status, 'row_count_check': run.row_count_check}, ensure_ascii=False)}\n\n"
            return
        # 2. 订阅 pub/sub
        pubsub = redis_client.redis_client().pubsub()
        await pubsub.subscribe(channel)
        try:
            idle = 0
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=2.0)
                if msg is None:
                    idle += 1
                    # 终态兜底轮询（pub/sub 丢消息保护，纪律 #15）
                    if idle % 5 == 0:
                        cur = await _current_status(run_id)
                        if cur in TERMINAL:
                            yield f"event: done\ndata: {json.dumps({'status': cur}, ensure_ascii=False)}\n\n"
                            return
                    if idle > 450:  # 15 分钟无事件超时关流（前端会重连）
                        return
                    continue
                idle = 0
                payload = json.loads(msg["data"])
                event = payload.pop("event", "status")
                yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
                if payload.get("status") in TERMINAL:
                    return
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


async def _current_status(run_id: int) -> str | None:
    from app.core.db import make_session_factory

    factory = make_session_factory()
    async with factory() as db:
        row = (await db.execute(select(ExecutionRun.status).where(ExecutionRun.id == run_id))).scalar_one_or_none()
    return row


@router.post("/versions/{version_id}/dry-run", status_code=202)
async def dry_run(
    version_id: int,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """受管试运行：P2 免四眼，签 Capability + Outbox + 账本，无准备单。"""
    v, project_id = await _version_and_project(db, version_id)
    if not await security.has_role_slot(db, project_id, user.id, "maker"):
        raise ApiError("E_FORBIDDEN_DUTY", "需要 maker 职责槽资格")
    if not v.is_immutable:
        raise ApiError("E_VALID_REQUEST", "版本未冻结，不能试运行")
    # 1. PDP 评级（预期 P2 免四眼）
    intent = ToolIntent(tool="dry_run", version_id=version_id, project_id=project_id,
                        subject_id=user.id, resource_scope={}, data_classification="internal", params={})
    decision = evaluate(intent)
    # 2. 单事务：Capability + ExecutionRun(run_kind=dry_run) + Outbox + 账本
    async with atomic() as tx:
        token = await capability.issue(tx, "dry_run", user.id, v.artifact_digest)
        run = ExecutionRun(
            version_id=version_id, preparation_id=None, run_kind="dry_run",
            capability_token_digest=hashlib.sha256(token.encode()).hexdigest(),
            status="pending", row_count_check="pending",
        )
        tx.add(run)
        await tx.flush()
        await outbox.emit(tx, "dry_run", run.id, "dry_run",
                          {"execution_run_id": run.id, "version_id": version_id,
                           "token": token, "project_id": project_id, "operator_id": user.id})
        evt = await append(tx, project_id, user.id, "dry_run", "execution_run", run.id,
                           {"version_id": version_id, "risk_level": decision.risk_level})
        await tx.commit()
    return {"execution_run_id": run.id, "audit_event_id": evt.id, "status": "pending"}


async def _ops_gate(db: AsyncSession, run_id: int, user, tool: str) -> tuple[ExecutionRun, int, dict]:
    """运维操作公共前置：operator 资格 + run 存在。"""
    run, project_id = await _run_and_project(db, run_id)
    if not await security.has_role_slot(db, project_id, user.id, "operator"):
        raise ApiError("E_FORBIDDEN_DUTY", "需要 operator 职责槽资格")
    return run, project_id, {}


@router.post("/execution-runs/{run_id}/cancel", status_code=202)
async def cancel_run(
    run_id: int, user=Depends(security.current_user), db: AsyncSession = Depends(get_session)
) -> dict:
    """取消：仅 pending/running 可取消；经 Outbox 下发 kill。"""
    run, project_id, _ = await _ops_gate(db, run_id, user, "cancel")
    if run.status not in ("pending", "running"):
        raise ApiError("E_RUN_INVALID_STATE", f"状态 {run.status} 不可取消")
    async with atomic() as tx:
        token = await capability.issue(tx, "cancel", user.id, f"run:{run_id}")
        await outbox.emit(tx, "execution_run", run_id, "cancel_run",
                          {"execution_run_id": run_id, "engine_job_id": run.engine_job_id,
                           "token": token, "project_id": project_id, "operator_id": user.id})
        evt = await append(tx, project_id, user.id, "cancel", "execution_run", run_id, {})
        await tx.commit()
    return {"id": run_id, "status": "cancelling", "audit_event_id": evt.id}


@router.post("/execution-runs/{run_id}/rollback", status_code=202)
async def rollback_run(
    run_id: int, user=Depends(security.current_user), db: AsyncSession = Depends(get_session)
) -> dict:
    """受管回滚：仅 succeeded 可回滚（swap 反向互换，从 __bak 恢复）。"""
    run, project_id, _ = await _ops_gate(db, run_id, user, "rollback")
    if run.status != "succeeded":
        raise ApiError("E_RUN_INVALID_STATE", f"状态 {run.status} 不可回滚（仅 succeeded）")
    async with atomic() as tx:
        token = await capability.issue(tx, "rollback", user.id, f"run:{run_id}")
        await outbox.emit(tx, "execution_run", run_id, "rollback",
                          {"execution_run_id": run_id, "version_id": run.version_id,
                           "token": token, "project_id": project_id, "operator_id": user.id})
        evt = await append(tx, project_id, user.id, "rollback", "execution_run", run_id, {})
        await tx.commit()
    return {"id": run_id, "status": "rolling_back", "audit_event_id": evt.id}


@router.post("/execution-runs/{run_id}/rerun", status_code=201)
async def rerun(
    run_id: int, user=Depends(security.current_user), db: AsyncSession = Depends(get_session)
) -> dict:
    """安全重跑（R6）：终态 run + 复用 Preparation + 指纹重算 + 新 Capability/Run/Outbox。"""
    # 1. 前置
    run, project_id, _ = await _ops_gate(db, run_id, user, "rerun")
    if run.status not in TERMINAL:
        raise ApiError("E_RUN_INVALID_STATE", "仅终态 run 可重跑")
    if run.run_kind != "execute" or run.preparation_id is None:
        raise ApiError("E_RUN_INVALID_STATE", "dry_run 不支持重跑，请重新触发 dry-run")
    prep = (await db.execute(select(Preparation).where(Preparation.id == run.preparation_id))).scalar_one()
    v = (await db.execute(select(PipelineVersion).where(PipelineVersion.id == run.version_id))).scalar_one()
    # 2. 指纹重算比对
    fingerprint = compute_fingerprint(v, v.etl_plan_json or {})
    if fingerprint != prep.input_fingerprint:
        raise ApiError("E_FINGERPRINT_MISMATCH", "制品指纹不一致，需重新 Prepare")
    # 3. 单事务新 run + Outbox
    async with atomic() as tx:
        token = await capability.issue(tx, "execute_pipeline", user.id, v.artifact_digest)
        new_run = ExecutionRun(
            version_id=v.id, preparation_id=prep.id, run_kind="execute",
            capability_token_digest=hashlib.sha256(token.encode()).hexdigest(),
            status="pending", row_count_check="pending",
        )
        tx.add(new_run)
        await tx.flush()
        await outbox.emit(tx, "execution_run", new_run.id, "execute_pipeline",
                          {"execution_run_id": new_run.id, "version_id": v.id, "token": token,
                           "project_id": project_id, "operator_id": user.id})
        evt = await append(tx, project_id, user.id, "rerun", "execution_run", new_run.id,
                           {"rerun_of": run_id})
        await tx.commit()
    return {"execution_run_id": new_run.id, "rerun_of": run_id, "audit_event_id": evt.id}
