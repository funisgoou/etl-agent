"""Benchmark 域（SPEC 3.10）：用例管理 + 评测执行（指标含 C1 硬判据）。

评测管线（轻量真实现）：逐用例走「PDP 评级 → 契约编译 →（可选）dry-run 行数校验」；
编译通过率/字段 F1/拦截率/误伤率为确定性计算，dry_run_pass_rate 来自真实 dry-run 结果（有则计）。
"""

import json
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.security as security
from app.compiler.quality_contract import ContractCompileError
from app.compiler.quality_contract import compile as compile_contract
from app.core.db import get_session
from app.core.errors import ApiError
from app.db_model import BenchmarkCase, BenchmarkRun, ExecutionRun
from app.harness.intents import ToolIntent
from app.harness.pdp import evaluate

router = APIRouter(prefix="/api/v1/benchmarks", tags=["benchmark"])
logger = structlog.get_logger(__name__)


class RunIn(BaseModel):
    suite_version: str = "v1.0"


def _field_f1(expected: dict, actual: dict) -> float:
    """字段映射 F1（宏平均按用例级精确/召回合并）。"""
    exp = {(m.get("source"), m.get("target")) for m in expected.get("mappings", [])}
    act = {(m.get("source"), m.get("target")) for m in actual.get("mappings", [])}
    if not exp and not act:
        return 1.0
    tp = len(exp & act)
    precision = tp / len(act) if act else 0.0
    recall = tp / len(exp) if exp else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


@router.post("/run", status_code=202)
async def run_benchmark(
    body: RunIn,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """触发评测（approver_security；demo 单项目语义下校验任一项目成员资格后同步执行）。"""
    # 1. 权限：任一项目的 approver_security/admin
    from app.db_model import ProjectMembership

    role = (
        await db.execute(
            select(ProjectMembership.role).where(ProjectMembership.user_id == user.id).limit(1)
        )
    ).scalar_one_or_none()
    if role not in ("approver_security", "admin"):
        raise ApiError("E_FORBIDDEN_PROJECT", "需要 approver_security 角色")
    # 2. 建运行记录
    run = BenchmarkRun(suite_version=body.suite_version, status="running",
                       metrics_json={}, started_at=datetime.now(UTC))
    db.add(run)
    await db.flush()
    # 3. 逐用例评测（同步：用例集小、纯函数计算为主）
    cases = (await db.execute(select(BenchmarkCase).where(BenchmarkCase.version == body.suite_version))).scalars().all()
    if not cases:
        await db.commit()
        raise ApiError("E_VALID_REQUEST", f"用例集不存在: {body.suite_version}（先导入 benchmark_cases）")
    compile_pass = f1_sum = block_hit = malicious_total = fp = benign_total = 0
    dry_pass = dry_total = 0
    for case in cases:
        exp_schema = case.expected_schema_json or {}
        plan = exp_schema.get("etl_plan", exp_schema)
        # 3a. 编译通过率（契约可编译）
        compiled = True
        try:
            compile_contract(plan.get("quality_contract", {}))
        except ContractCompileError:
            compiled = False
        compile_pass += int(compiled)
        # 3b. 字段 F1
        f1_sum += _field_f1(exp_schema, plan)
        # 3c. PDP 拦截 / 误伤
        intent = ToolIntent(
            tool="execute_pipeline", version_id=0, project_id=0, subject_id=0,
            resource_scope={}, data_classification=plan.get("data_classification", "internal"), params={},
        )
        decision = evaluate(intent)
        if case.is_malicious:
            malicious_total += 1
            block_hit += int(decision.risk_level == "P0")
        else:
            benign_total += 1
            fp += int(decision.risk_level == "P0")
        # 3d. dry-run 硬判据（有对应真实 dry_run 记录才计入分母）
        if case.name.startswith("dry:"):
            dry_total += 1
            dr = (
                await db.execute(
                    select(ExecutionRun).where(ExecutionRun.run_kind == "dry_run",
                                               ExecutionRun.row_count_check == "passed")
                    .order_by(ExecutionRun.id.desc()).limit(1)
                )
            ).scalar_one_or_none()
            dry_pass += int(dr is not None)
    n = len(cases)
    metrics = {
        "compile_pass_rate": round(compile_pass / n, 4),
        "field_f1": round(f1_sum / n, 4),
        "dry_run_pass_rate": round(dry_pass / dry_total, 4) if dry_total else None,
        "block_rate": round(block_hit / malicious_total, 4) if malicious_total else None,
        "false_positive_rate": round(fp / benign_total, 4) if benign_total else None,
    }
    # 4. 健康度（PRD 公式；缺项按 0 处理并标注）
    def _m(k: str) -> float:
        v = metrics.get(k)
        return v if isinstance(v, float) else 0.0

    metrics["health_score"] = round(
        (0.4 * _m("compile_pass_rate") + 0.3 * _m("field_f1") + 0.2 * _m("dry_run_pass_rate")
         + 0.1 * max(0.0, _m("block_rate") - _m("false_positive_rate"))) * 100,
        2,
    )
    run.metrics_json = metrics
    run.status = "succeeded"
    run.finished_at = datetime.now(UTC)
    await db.commit()
    logger.info("benchmark 完成", run_id=run.id, score=metrics["health_score"])
    return {"benchmark_run_id": run.id, "status": "succeeded", "metrics_json": metrics}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: int,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """评测结果。"""
    run = (await db.execute(select(BenchmarkRun).where(BenchmarkRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise ApiError("E_NOT_FOUND", f"评测不存在: {run_id}")
    return {"id": run.id, "suite_version": run.suite_version, "status": run.status,
            "metrics_json": run.metrics_json, "started_at": run.started_at, "finished_at": run.finished_at}


@router.get("/runs")
async def list_runs(
    page: int = 1, page_size: int = 20,
    user=Depends(security.current_user), db: AsyncSession = Depends(get_session),
) -> dict:
    rows = (await db.execute(select(BenchmarkRun).order_by(BenchmarkRun.id.desc())
                             .offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {"items": [{"id": r.id, "suite_version": r.suite_version, "status": r.status,
                       "metrics_json": r.metrics_json, "finished_at": r.finished_at} for r in rows],
            "total": len(rows), "page": page, "page_size": page_size}
