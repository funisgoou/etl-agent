"""Studio 域（SPEC 3.7）：触发生成、澄清回答恢复、run 投影查询。

恢复唯一真相源 = PostgresSaver checkpoint（D10）；本域只写 agent_runs 投影。
"""

import asyncio
import json
import uuid

import structlog
from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.security as security
from app.agent.graph import get_checkpointer, get_graph, new_thread_id
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.core.logging import new_trace_id
from app.db_model import AgentRun, Pipeline, PipelineVersion

router = APIRouter(prefix="/api/v1", tags=["studio"])
logger = structlog.get_logger(__name__)


class GenerationIn(BaseModel):
    prompt: str


class AnswerIn(BaseModel):
    answer: dict


async def _version_ctx(db: AsyncSession, version_id: int) -> tuple[PipelineVersion, int]:
    """取版本与项目 ID。"""
    v = (await db.execute(select(PipelineVersion).where(PipelineVersion.id == version_id))).scalar_one_or_none()
    if v is None:
        raise ApiError("E_NOT_FOUND", f"版本不存在: {version_id}")
    p = (await db.execute(select(Pipeline).where(Pipeline.id == v.pipeline_id))).scalar_one()
    return v, p.project_id


def _project_run(state: dict) -> tuple[str, dict | None, str | None]:
    """状态 → 投影字段（status, pending_question, error）。"""
    if state.get("status") == "waiting_input":
        pq = state.get("_interrupt_payload") or {}
        return "waiting_input", pq, None
    if state.get("status") == "failed":
        return "failed", None, state.get("error")
    if state.get("gate_report", {}).get("passed") if state.get("gate_report") else False:
        return "succeeded", None, None
    return ("running", None, None)


async def _run_graph_and_persist(run_id: int, thread_id: str, init_state: dict) -> None:
    """后台执行状态机并把终态/中断写回 agent_runs 投影。

    interrupt 发生时 LangGraph 返回 __interrupt__ 信息；此处解出提问表单存投影。
    """
    new_trace_id()
    from app.core.db import make_session_factory

    factory = make_session_factory()  # 独立事件循环专用（后台任务）
    try:
        async with get_checkpointer() as cp:
            await cp.setup()
            graph = get_graph(cp)
            config = {"configurable": {"thread_id": thread_id}}
            result = await graph.ainvoke(init_state, config=config)
            # 1. interrupt 检测
            state_snapshot = await graph.aget_state(config)
            interrupt_info = state_snapshot.next  # 非空 = 挂起在 interrupt
            status = "running"
            pending_q = None
            error = None
            if interrupt_info:
                status = "waiting_input"
                intr = state_snapshot.tasks
                # 取第一个 interrupt 的 payload
                for task in intr.values():
                    if getattr(task, "interrupts", None):
                        pending_q = task.interrupts[0].value
                        break
            elif result.get("status") == "failed":
                status, error = "failed", result.get("error")
            elif (result.get("gate_report") or {}).get("passed"):
                status = "succeeded"
            # 2. 设计成果写回版本（生成完成时）
            if status == "succeeded":
                async with factory() as db:
                    v = (await db.execute(select(PipelineVersion).where(PipelineVersion.id == init_state["version_id"]))).scalar_one()
                    v.etl_plan_json = result.get("etl_plan") or {}
                    v.hocon_text = result.get("hocon") or ""
                    v.gate_report_json = dict(result.get("gate_report") or {})
                    await db.commit()
            # 3. 投影更新
            async with factory() as db:
                run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one()
                run.status = status
                run.step_count = len(result.get("step_trace", []))
                run.error_message = error
                run.pending_question_json = pending_q
                await db.commit()
            logger.info("agent_run_finished", run_id=run_id, status=status)
    except Exception as exc:
        logger.error(f"agent_run 执行失败:{exc}")
        async with factory() as db:
            run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one_or_none()
            if run:
                run.status = "failed"
                run.error_message = str(exc)
                await db.commit()


@router.post("/versions/{version_id}/generation", status_code=202)
async def start_generation(
    version_id: int,
    body: GenerationIn,
    bg: BackgroundTasks,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """触发生成：建 agent_run 投影 + 后台跑图（interrupt 由 checkpoint 持久化）。"""
    v, project_id = await _version_ctx(db, version_id)
    if not await security.has_role_slot(db, project_id, user.id, "maker"):
        raise ApiError("E_FORBIDDEN_DUTY", "需要 maker 职责槽资格")
    if v.is_immutable:
        raise ApiError("E_VALID_REQUEST", "版本已冻结，不能重新生成")
    # 1. 同版本并发护栏：存在进行中的 run 则拒绝
    active = (
        await db.execute(
            select(AgentRun.id).where(
                AgentRun.version_id == version_id, AgentRun.status.in_(("running", "waiting_input"))
            )
        )
    ).scalar_one_or_none()
    if active:
        raise ApiError("E_VALID_REQUEST", f"存在进行中的生成任务: {active}（先回答澄清或等待完成）")
    # 2. 投影落库（独立事务提交，避免请求会话时序问题——纪律 #6）
    thread_id = new_thread_id(version_id)
    run = AgentRun(version_id=version_id, thread_id=thread_id, prompt=body.prompt, status="running")
    db.add(run)
    await db.commit()
    # 3. 后台执行（BackgroundTasks 与请求同循环；新会话工厂后台自建）
    init_state = {
        "version_id": version_id, "project_id": project_id, "thread_id": thread_id,
        "prompt": body.prompt, "clarifications": [], "step_trace": [], "repair_round": 0,
    }
    bg.add_task(_run_graph_and_persist, run.id, thread_id, init_state)
    return {"run_id": run.id, "thread_id": thread_id, "status": "running"}


@router.get("/agent-runs/{run_id}")
async def get_run(
    run_id: int,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """生成状态查询（轮询）。"""
    run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise ApiError("E_NOT_FOUND", f"agent-run 不存在: {run_id}")
    v, project_id = await _version_ctx(db, run.version_id)
    await security.require_member(project_id)(user, db)
    pq = run.pending_question_json
    # waiting_input 时输出前端 schema 驱动表单（{message, fields:[{key,label,type,value,required}]}）
    pending_question = None
    if run.status == "waiting_input" and pq:
        fields = pq.get("missing", [])
        questions = pq.get("questions", {})
        LABELS = {"target_table": "目标 Doris 表名", "source_table": "源表名"}
        form_fields = [
            {
                "key": f,
                "label": LABELS.get(f, f),
                "type": "text",
                "required": True,
                **({"value": "dwd_orders"} if f == "target_table" else {}),
            }
            for f in fields
            if f in ("target_table", "source_table")  # 系统级缺失（连接不存在）不进表单
        ]
        if form_fields:
            pending_question = {
                "message": "；".join(questions.get(f, f"请补充 {f}") for f in fields),
                "fields": form_fields,
            }
    return {"run_id": run.id, "version_id": run.version_id, "thread_id": run.thread_id,
            "status": run.status, "step_count": run.step_count,
            "steps": _steps_timeline(run.status, run.step_count or 0),
            "error_message": run.error_message,
            "pending_question": pending_question}


def _steps_timeline(status: str, step_count: int) -> list[dict]:
    """四步时间线：意图解析→元数据探查→生成配置→门禁校验（前端 AgentRunStep 契约）。"""
    names = ["意图解析", "元数据探查", "生成配置", "门禁校验"]
    reached = min(step_count, 4) if status != "waiting_input" else min(step_count, 2)
    if status == "succeeded":
        return [{"name": n, "status": "done"} for n in names]
    return [
        {"name": n, "status": "done" if i < reached else ("running" if i == reached and status == "running" else "pending")}
        for i, n in enumerate(names)
    ]


@router.post("/agent-runs/{run_id}/answers", status_code=202)
async def submit_answer(
    run_id: int,
    body: AnswerIn,
    bg: BackgroundTasks,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """提交澄清回答：Command(resume) 从 checkpoint 恢复状态机（D10）。"""
    from langgraph.types import Command

    run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one_or_none()
    if run is None:
        raise ApiError("E_NOT_FOUND", f"agent-run 不存在: {run_id}")
    v, project_id = await _version_ctx(db, run.version_id)
    if not await security.has_role_slot(db, project_id, user.id, "maker"):
        raise ApiError("E_FORBIDDEN_DUTY", "需要 maker 职责槽资格")
    if run.status != "waiting_input":
        raise ApiError("E_VALID_REQUEST", f"当前状态 {run.status} 无需澄清")
    # 1. 投影先置 running
    run.status = "running"
    run.pending_question_json = None
    await db.commit()
    # 2. 后台恢复执行
    bg.add_task(_resume_graph_and_persist, run.id, run.thread_id, body.answer, run.version_id)
    return {"run_id": run.id, "status": "running"}


async def _resume_graph_and_persist(run_id: int, thread_id: str, answer: dict, version_id: int) -> None:
    """从 checkpoint 恢复：answer 直接作为 interrupt 返回值。"""
    from langgraph.types import Command

    new_trace_id()
    from app.core.db import make_session_factory

    factory = make_session_factory()
    try:
        async with get_checkpointer() as cp:
            await cp.setup()
            graph = get_graph(cp)
            config = {"configurable": {"thread_id": thread_id}}
            result = await graph.ainvoke(Command(resume=answer), config=config)
            state_snapshot = await graph.aget_state(config)
            status, pending_q, error = "running", None, None
            if state_snapshot.next:
                status = "waiting_input"
                for task in state_snapshot.tasks.values():
                    if getattr(task, "interrupts", None):
                        pending_q = task.interrupts[0].value
                        break
            elif result.get("status") == "failed":
                status, error = "failed", result.get("error")
            elif (result.get("gate_report") or {}).get("passed"):
                status = "succeeded"
            if status == "succeeded":
                async with factory() as db:
                    v = (await db.execute(select(PipelineVersion).where(PipelineVersion.id == version_id))).scalar_one()
                    v.etl_plan_json = result.get("etl_plan") or {}
                    v.hocon_text = result.get("hocon") or ""
                    v.gate_report_json = dict(result.get("gate_report") or {})
                    await db.commit()
            async with factory() as db:
                run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one()
                run.status = status
                run.step_count = len(result.get("step_trace", []))
                run.error_message = error
                run.pending_question_json = pending_q
                await db.commit()
    except Exception as exc:
        logger.error(f"agent_run 恢复失败:{exc}")
        async with factory() as db:
            run = (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one_or_none()
            if run:
                run.status = "failed"
                run.error_message = str(exc)
                await db.commit()
