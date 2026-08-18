"""运行时监督与诊断（SPEC 7.3/7.4）：预算检查 + 快照落库 + 根因诊断。"""

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import make_session_factory
from app.core.redis_client import publish_status
from app.db_model import ExecutionRun, RuntimeSupervisionSnapshot

logger = structlog.get_logger(__name__)


def check_budget(metrics: dict, budget: dict) -> tuple[str, str]:
    """对照预算决策：ok/warning/breach + 动作。

    Returns:
        (decision, action)：breach → kill_job；warning → alert；ok → none。
    """
    # 1. 行数预算
    if metrics.get("input_records", 0) > budget.get("max_read_rows", 10**9):
        return "breach", "kill_job"
    # 2. 字节预算
    if metrics.get("bytes_processed", 0) > budget.get("max_write_bytes", 2**31):
        return "breach", "kill_job"
    # 3. 时长预算
    if metrics.get("duration_seconds", 0) > budget.get("max_duration_seconds", 1800):
        return "breach", "kill_job"
    # 4. 错误拒绝率（>50% 预警：源数据质量异常）
    inp = metrics.get("input_records") or 0
    err = metrics.get("error_records") or 0
    if inp > 0 and err / inp > 0.5:
        return "warning", "alert"
    return "ok", "none"


async def snapshot_and_decide(run_id: int, metrics: dict, budget: dict) -> tuple[str, str]:
    """监督快照落库 + 推送（Worker 每阶段调用）。"""
    decision, action = check_budget(metrics, budget)
    factory = make_session_factory()
    async with factory() as db:
        db.add(RuntimeSupervisionSnapshot(execution_run_id=run_id, metrics_json=metrics,
                                          decision=decision, action_taken=action))
        await db.commit()
    if decision != "ok":
        publish_status(run_id, {"event": "supervision", "decision": decision,
                                "metrics": metrics, "action": action})
        logger.warning("监督越线", run_id=run_id, decision=decision, action=action)
    return decision, action


def diagnose(error_ctx: dict) -> dict:
    """可解释根因诊断（确定性规则优先，SPEC 7.4）。

    Returns:
        {"root_cause": str, "suggestions": [str]}。
    """
    err = (error_ctx.get("error") or "").lower()
    stage = error_ctx.get("sub_stage", "")
    # 1. 规则表
    rules: list[tuple[str, str, list[str]]] = [
        ("connection refused", "数据面连接失败", ["检查目标 Doris/源库容器是否健康", "核对连接配置地址与端口"]),
        ("access denied", "凭据无效", ["检查连接用户名/密码（Vault 引用是否过期）", "确认账号权限"]),
        ("rowcount", "行数一致性校验失败（C1）", ["核对源表行数与 input_records", "检查分流 SQL 过滤条件是否全量覆盖"]),
        ("budget", "运行预算越限", ["在准备单中申请更高预算", "或缩小同步范围/采样"]),
        ("replication_num", "Doris 建表被拒", ["单 BE 环境需 replication_num=1（已内置，检查集群状态）"]),
        ("jobid", "SeaTunnel 作业异常", ["查看 seatunnel 容器日志", "确认 hazelcast REST 开启且作业体为 JSON"]),
        ("syntax", "SQL 语法错误", ["检查质量契约列名与算子（门禁编译产物）"]),
    ]
    for key, cause, suggestions in rules:
        if key in err:
            return {"root_cause": f"[{stage}] {cause}", "suggestions": suggestions}
    # 2. 兜底
    return {
        "root_cause": f"[{stage}] 未分类异常: {error_ctx.get('error', '')[:200]}",
        "suggestions": ["查看运行日志与监督快照", "联系平台管理员"],
    }


def quality_report(run: ExecutionRun, err_distribution: dict | None = None) -> dict:
    """质量报告构造（C1 双等式判定 + 错误码分布）。"""
    inp = run.input_records or 0
    out = run.output_records or 0
    err = run.error_records or 0
    # 1. 双等式（② 合计守恒；① 与源端基准在任务里比对）
    eq2 = (out + err) == inp if inp else False
    eq1 = run.row_count_check != "failed"
    passed = eq1 and eq2 and inp > 0
    return {
        "row_count_check": "passed" if passed else "failed",
        "error_code_distribution": err_distribution or {},
        "input_records": inp, "output_records": out, "error_records": err,
        "checked_at": datetime.now(UTC).isoformat(),
    }
