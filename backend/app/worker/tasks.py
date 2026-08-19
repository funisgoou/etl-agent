"""Celery 任务（SPEC 7.1/7.2）：三阶段执行状态机 COPYING → SPLITTING → SWAPPING。

副作用唯一出口纪律：任务由 Outbox 命令驱动，执行前经 broker 验签消费 Capability；
SeaTunnel/Doris 触达仅存在于本模块（CI 静态检查点）。
"""

import asyncio
import json
import time
from datetime import UTC, datetime

import structlog
from celery import shared_task

from app.compiler.quality_contract import compile as compile_contract
from app.core import redis_client
from app.core.config import get_settings
from app.core.db import make_session_factory
from app.core.secret_provider import resolve_config
from app.harness import capability
from app.harness.intents import ToolIntent
from app.worker import seatunnel_client
from app.worker.doris_client import Doris
from app.worker.supervision import diagnose, quality_report, snapshot_and_decide

logger = structlog.get_logger(__name__)


def _publish(run_id: int, **kw) -> None:
    """状态推送（Redis pub/sub → SSE）。"""
    try:
        redis_client.publish_status(run_id, kw)
    except Exception:  # noqa: BLE001
        pass


async def _execute_pipeline(payload: dict) -> None:
    """主执行链：验签 → 建表族 → COPYING → SPLITTING → SWAPPING → C1 校验。"""
    run_id = payload["execution_run_id"]
    version_id = payload["version_id"]
    token = payload["token"]
    factory = make_session_factory()
    s = get_settings()

    # 1. 会话内：验签消费 + 取版本与连接配置（按事件类型验签：execute_pipeline / dry_run）
    tool = "dry_run" if payload.get("event_type") == "dry_run" else "execute_pipeline"
    async with factory() as db:
        from sqlalchemy import select

        from app.db_model import Connection, ExecutionRun, PipelineVersion

        v = (await db.execute(select(PipelineVersion).where(PipelineVersion.id == version_id))).scalar_one()
        plan = v.etl_plan_json or {}
        contract = plan.get("quality_contract", {})
        source = plan.get("source", {})
        target_table = plan.get("target", {}).get("table") or contract.get("table")
        run = (await db.execute(select(ExecutionRun).where(ExecutionRun.id == run_id))).scalar_one()
        budget = {"max_read_rows": 10**6, "max_write_bytes": 2 * 2**30, "max_duration_seconds": 1800}
        # 验签消费（Replay Guard 单事务置位）
        intent = ToolIntent(tool="execute_pipeline", version_id=version_id,
                            project_id=payload["project_id"], subject_id=payload["operator_id"],
                            resource_scope={}, data_classification=plan.get("data_classification", "internal"),
                            params={"execution_run_id": run_id})
        claims = await capability.verify_and_consume(db, token, tool, v.artifact_digest)
        await db.commit()
        # 源/目标连接物化（resolve_config 唯一物化点）
        src_cfg: dict = {}
        if source.get("connection_id"):
            conn = (await db.execute(select(Connection).where(Connection.id == source["connection_id"]))).scalar_one()
            rc = resolve_config(conn.config_json)
            src_cfg = {"kind": "mysql", "table": source["table"],
                       "url": f"jdbc:mysql://{rc['host']}:{rc.get('port', 3306)}/{rc['database']}",
                       "user": rc["username"], "password": rc.get("password", "")}
        else:
            from app.db_model import FileAsset

            asset = (await db.execute(select(FileAsset).where(FileAsset.id == source["file_asset_id"]))).scalar_one()
            src_cfg = {"kind": "csv", "file_path": asset.file_path,
                       "minio_endpoint": _engine_minio_endpoint(), "minio_access_key": s.minio_access_key,
                       "minio_secret_key": s.minio_secret_key}
        dry = run.run_kind == "dry_run"
        db_name = s.doris_dryrun_database if dry else s.doris_database
        columns = [c if isinstance(c, str) else c.get("name") for c in
                   (plan.get("mappings") and [m["source"] for m in plan["mappings"]] or contract.get("columns", []))]

    doris = Doris(db_name)
    t0 = time.monotonic()

    async def _update(**kw) -> None:
        async with factory() as db:
            from sqlalchemy import select

            from app.db_model import ExecutionRun as ER

            r = (await db.execute(select(ER).where(ER.id == run_id))).scalar_one()
            for k, val in kw.items():
                setattr(r, k, val)
            await db.commit()

    try:
        # 2. 置 running + 源端行数基准（C1 判据①）
        src_count = await _source_row_count(src_cfg, s.dry_run_sample_limit if dry else None)
        await _update(status="running", sub_stage="COPYING", started_at=datetime.now(UTC),
                      source_row_count=src_count)
        _publish(run_id, event="status", status="running", sub_stage="COPYING")
        # 3. 表族就绪（dry-run 库独立，跳过 Swap）；按源 profile 真实类型建表，key 列补精确类型
        cols_def = _columns_def(plan.get("_source_columns") or [], columns)
        await doris.ensure_table_family(target_table, cols_def)
        await doris.truncate_raw(target_table)
        await doris.rebuild_shadow(target_table)
        # 4. COPYING：SeaTunnel 搬运 源 → {t}__raw
        job = seatunnel_client.build_job_json(
            mode="dry_run" if dry else "execute", source=src_cfg, target_table=f"{target_table}__raw",
            target_db=db_name, doris_user=s.doris_user, doris_password=s.doris_password,
            doris_host_for_engine=_engine_doris_host(), doris_port_for_engine=s.doris_port,
            columns=columns, sample_limit=s.dry_run_sample_limit if dry else None,
        )
        job_id = await seatunnel_client.submit_job(job, f"etl-agent-{run_id}")
        await _update(engine_job_id=job_id)
        await _wait_job(job_id)
        raw_count = await doris.count(f"{target_table}__raw")
        await _update(input_records=raw_count, bytes_processed=raw_count * 256)
        decision, action = await snapshot_and_decide(run_id, {"input_records": raw_count}, budget)
        if decision == "breach":
            raise RuntimeError(f"budget breach at COPYING: input={raw_count}")
        elapsed_copy = max(int(time.monotonic() - t0), 1)
        _publish(run_id, event="metrics", input_records=raw_count, sub_stage="COPYING",
                 throughput_rps=int(raw_count / elapsed_copy), bytes_processed=raw_count * 256)
        # 5. SPLITTING：受管分流 SQL（编译产物，__err 附错误码）
        await _update(sub_stage="SPLITTING")
        _publish(run_id, event="status", status="running", sub_stage="SPLITTING")
        split = compile_contract(contract, table=target_table)
        await doris.exec(split.shadow_sql)
        await doris.exec(split.err_sql)
        out_count = await doris.count(f"{target_table}__shadow")
        err_count = await doris.count(f"{target_table}__err")
        await _update(output_records=out_count, error_records=err_count)
        # 错误码分布
        try:
            rows = await doris.exec(f"SELECT `__error_code`, COUNT(*) FROM `{target_table}__err` GROUP BY `__error_code`")
            err_dist = {str(r[0]): int(r[1]) for r in rows}
        except Exception:  # noqa: BLE001
            err_dist = {}
        decision, action = await snapshot_and_decide(
            run_id, {"input_records": raw_count, "output_records": out_count, "error_records": err_count,
                     "duration_seconds": int(time.monotonic() - t0)}, budget)
        if decision == "breach":
            raise RuntimeError(f"budget breach at SPLITTING: {out_count}/{err_count}")
        elapsed_total = max(int(time.monotonic() - t0), 1)
        _publish(run_id, event="metrics", input_records=raw_count, output_records=out_count,
                 error_records=err_count, sub_stage="SPLITTING",
                 throughput_rps=int((out_count + err_count) / elapsed_total))
        # 6. C1 双等式硬判据
        expected = min(src_count, s.dry_run_sample_limit) if dry and src_count else src_count
        c1 = (raw_count == expected) and (out_count + err_count == raw_count)
        # 7. SWAPPING（dry-run 跳过）
        if c1 and not dry:
            await _update(sub_stage="SWAPPING")
            _publish(run_id, event="status", status="running", sub_stage="SWAPPING")
            await doris.ensure_main_table(target_table, cols_def)
            await doris.atomic_swap(target_table)
        # 8. 终态落库
        status = "succeeded" if c1 else "failed"
        async with factory() as db:
            from sqlalchemy import select

            from app.db_model import ExecutionRun as ER

            r = (await db.execute(select(ER).where(ER.id == run_id))).scalar_one()
            r.status = status
            r.sub_stage = None
            r.finished_at = datetime.now(UTC)
            r.row_count_check = "passed" if c1 else "failed"
            r.diagnosis_json = {"quality_report": quality_report(r, err_dist)} if c1 else {
                **diagnose({"error": f"rowcount mismatch src={src_count} raw={raw_count} out={out_count} err={err_count}",
                            "sub_stage": "SPLITTING"}),
                "quality_report": quality_report(r, err_dist),
            }
            await db.commit()
        _publish(run_id, event="done", status=status, row_count_check=r.row_count_check)
        logger.info("执行完成", run_id=run_id, status=status, out=out_count, err=err_count)
    except Exception as exc:
        logger.error(f"执行失败:{exc}")
        async with factory() as db:
            from sqlalchemy import select

            from app.db_model import ExecutionRun as ER

            r = (await db.execute(select(ER).where(ER.id == run_id))).scalar_one()
            r.status = "failed"
            r.sub_stage = None
            r.finished_at = datetime.now(UTC)
            r.diagnosis_json = diagnose({"error": str(exc), "sub_stage": r.sub_stage or "COPYING"})
            await db.commit()
        _publish(run_id, event="done", status="failed")


# Doris 类型映射：key 列（id）用精确类型，其余 STRING（哑管道保真，分流期不做类型转换）
_DORIS_KEY_TYPES = {"bigint": "BIGINT", "int": "INT", "integer": "INT", "id": "BIGINT"}


def _columns_def(source_columns: list, columns: list[str]) -> str:
    """列定义构造：key 列 id 用 BIGINT，其余 STRING（Doris 限制 key 列不可 STRING）。"""
    defs = []
    for c in columns:
        if c == "id":
            defs.append("`id` BIGINT")
        else:
            defs.append(f"`{c}` STRING")
    return ", ".join(defs) or "`id` BIGINT"


def _engine_doris_host() -> str:
    """SeaTunnel 容器视角的 Doris 地址（§4.3 双视角）。"""
    import os

    return os.environ.get("DORIS_HOST_ENGINE", get_settings().doris_host)


def _engine_minio_endpoint() -> str:
    """SeaTunnel 容器视角的 MinIO 地址。"""
    import os

    return os.environ.get("MINIO_ENDPOINT_ENGINE", get_settings().minio_endpoint)


async def _source_row_count(src_cfg: dict, limit: int | None) -> int:
    """源端行数基准（C1 判据①）。"""
    if src_cfg["kind"] == "mysql":
        # 从 jdbc url 反解连接（保持单一配置源）
        import re

        from app.domain.connectors.base import _mysql_query

        m = re.match(r"jdbc:mysql://([^:/]+):?(\d+)?/(\w+)", src_cfg["url"])
        host, port, database = m.group(1), int(m.group(2) or 3306), m.group(3)
        rows = await _mysql_query({"host": host, "port": port, "username": src_cfg["user"],
                                   "password": src_cfg["password"], "database": database},
                                  f"SELECT COUNT(*) FROM `{src_cfg['table']}`")
        cnt = int(rows[0][0])
        return min(cnt, limit) if limit else cnt
    # csv：无库可查，基准由搬运后校验（raw 即全量）
    return 0


async def _wait_job(job_id: str, timeout: int = 600) -> None:
    """轮询作业至终态。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = await seatunnel_client.job_status(job_id)
        if st["status"] == "FINISHED":
            return
        if st["status"] in ("FAILED", "CANCELED"):
            raise RuntimeError(f"SeaTunnel 作业终态 {st['status']}: {st['errorMsg']}")
        await asyncio.sleep(3)
    raise RuntimeError("SeaTunnel 作业超时")


@shared_task(name="app.worker.tasks.execute_pipeline")
def execute_pipeline_task(payload_json: str) -> str:
    """Celery 入口：Outbox relay 投递。"""
    asyncio.run(_execute_pipeline(json.loads(payload_json)))
    return "ok"


async def _cancel(payload: dict) -> None:
    """取消：kill SeaTunnel 作业 + run 置 cancelled（Capability 验签先行）。"""
    factory = make_session_factory()
    async with factory() as db:
        from sqlalchemy import select

        from app.db_model import ExecutionRun

        await capability.verify_and_consume(db, payload["token"], "cancel", None)
        run = (await db.execute(select(ExecutionRun).where(ExecutionRun.id == payload["execution_run_id"]))).scalar_one()
        if run.engine_job_id:
            await seatunnel_client.kill_job(run.engine_job_id)
        run.status = "cancelled"
        run.finished_at = datetime.now(UTC)
        run.sub_stage = None
        await db.commit()
    _publish(payload["execution_run_id"], event="done", status="cancelled")


@shared_task(name="app.worker.tasks.cancel_run")
def cancel_run_task(payload_json: str) -> str:
    asyncio.run(_cancel(json.loads(payload_json)))
    return "cancelled"


async def _rollback(payload: dict) -> None:
    """受管回滚：__bak 与正式表互换 + 状态置 rolled_back。"""
    factory = make_session_factory()
    s = get_settings()
    async with factory() as db:
        from sqlalchemy import select

        from app.db_model import ExecutionRun, PipelineVersion

        await capability.verify_and_consume(db, payload["token"], "rollback", None)
        run = (await db.execute(select(ExecutionRun).where(ExecutionRun.id == payload["execution_run_id"]))).scalar_one()
        v = (await db.execute(select(PipelineVersion).where(PipelineVersion.id == run.version_id))).scalar_one()
        target_table = (v.etl_plan_json or {}).get("target", {}).get("table")
        run.status = "rolled_back"
        run.finished_at = datetime.now(UTC)
        await db.commit()
    doris = Doris(s.doris_database)
    await doris.rollback_swap(target_table)
    _publish(payload["execution_run_id"], event="done", status="rolled_back")


@shared_task(name="app.worker.tasks.rollback")
def rollback_task(payload_json: str) -> str:
    asyncio.run(_rollback(json.loads(payload_json)))
    return "rolled_back"
