"""LangGraph 节点（SPEC 5.2）：意图解析 → 澄清 → 探查 → 生成 → 门禁 → 修复。

LLM 只做路由与参数抽取，不碰状态推进（确定性代码负责）。
"""

import json
import uuid
from typing import Any

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.state import GateFinding, GateReport, IntentSpec, StudioState
from app.compiler.quality_contract import ContractCompileError, compile as compile_contract
from app.core.llm_client import chat
from app.db_model import Connection, FileAsset, PipelineVersion

logger = structlog.get_logger(__name__)

# 意图抽取结构（LLM 数值/ID 一律不可信，服务端兜底）
class IntentDraft(BaseModel):
    """LLM 意图抽取产物（字段全部可空：LLM 缺省由服务端兜底，纪律 #8）。"""

    source_table: str | None = None
    target_table: str | None = Field(default=None, description="Doris 目标表名，如 dwd_orders")
    file_asset_id: int | None = None
    quality_requirements: list[dict] = Field(default_factory=list)
    data_classification: str | None = None
    questions: list[str] = Field(default_factory=list, description="缺失信息需要向用户确认的问题")


INTENT_SYSTEM = (
    "你是 ETL 需求解析器。从用户的自然语言需求中抽取结构化信息，只输出 JSON。"
    "可用的质量算子: not_null/positive/email_format/not_empty；脱敏算子: mask_email/mask_phone。"
    "源连接与目标连接由系统注入候选，不要猜测 ID。"
    "信息不足时在 questions 里列出要问用户的问题（每条一个问题，中文）。"
)


async def parse_intent(state: StudioState) -> dict:
    """意图解析：LLM 抽取 + 服务端补全连接 ID 与缺参判定。"""
    # 1. 服务端事实：项目内候选连接与文件资产（LLM 不猜 ID）
    from app.core.db import session_factory

    assert session_factory is not None
    async with session_factory() as db:
        conns = (
            await db.execute(
                select(Connection).where(Connection.project_id == state["project_id"])
            )
        ).scalars().all()
        assets = (
            await db.execute(select(FileAsset).where(FileAsset.project_id == state["project_id"]))
        ).scalars().all()
    conn_desc = [
        {"id": c.id, "type": c.conn_type, "name": c.name} for c in conns
    ]
    asset_desc = [{"id": a.id, "name": a.file_name} for a in assets]
    # 2. LLM 抽取
    draft = await chat(
        [
            {"role": "system", "content": INTENT_SYSTEM},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "需求": state["prompt"],
                        "可用连接": conn_desc,
                        "可用文件资产": asset_desc,
                        "要求": "抽取 source_table(源表名)/target_table/file_asset_id(仅当需求指明CSV文件时)/quality_requirements/column_mapping(可省)/data_classification",
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        schema=IntentDraft,
    )
    # 3. 服务端兜底：源/目标连接按类型匹配（mysql 源、doris 目标）
    src = next((c for c in conns if c.conn_type == "mysql"), None)
    tgt = next((c for c in conns if c.conn_type == "doris"), None)
    intent: IntentSpec = {
        "source_conn_id": src.id if src else None,
        "source_table": draft.source_table,
        "file_asset_id": draft.file_asset_id,
        "target_conn_id": tgt.id if tgt else None,
        "target_table": draft.target_table,
        "quality_requirements": draft.quality_requirements or [],
        "data_classification": draft.data_classification if draft.data_classification in
        ("public", "internal", "confidential", "secret") else "internal",
    }
    # 4. 缺参判定（确定性）：无源无文件 / 无目标表 / 无源表（mysql 源时）
    missing: list[str] = []
    if intent["source_conn_id"] is None and intent["file_asset_id"] is None:
        missing.append("source")
    if intent["source_conn_id"] is not None and not intent["source_table"]:
        missing.append("source_table")
    if not intent["target_table"]:
        missing.append("target_table")
    if not tgt:
        missing.append("target_conn")
    intent["missing"] = missing
    return {"intent": intent, "step_trace": ["parse_intent"]}


def _question_for(field: str, intent: IntentSpec) -> str:
    """缺参字段 → 人话提问。"""
    return {
        "source": "未找到 MySQL 源连接，请先在「数据连接」创建 MySQL 连接，或改用 CSV 文件资产。",
        "source_table": "要同步哪张源表？（如 orders）",
        "target_table": "目标 Doris 表名是什么？（如 dwd_orders）",
        "target_conn": "未找到 Doris 目标连接，请先在「数据连接」创建 Doris 连接。",
    }.get(field, f"请补充: {field}")


async def clarify(state: StudioState) -> dict:
    """澄清：缺参时 interrupt 提问（LangGraph 挂起，checkpoint 持久化）。"""
    from langgraph.types import interrupt

    intent = state["intent"] or {}
    missing = intent.get("missing", [])
    questions = {f: _question_for(f, intent) for f in missing}
    # interrupt 挂起：前端拿 pending_question 表单，回答经 answers 接口回填
    answer: dict = interrupt({"missing": missing, "questions": questions})
    # 2. 回答合入意图（target_table/source_table 等）
    updated: IntentSpec = {**intent}  # type: ignore[assignment]
    for f in missing:
        if f in answer and answer[f]:
            if f == "target_table":
                updated["target_table"] = str(answer[f])
            elif f == "source_table":
                updated["source_table"] = str(answer[f])
    updated["missing"] = [f for f in missing if f not in answer or not answer[f] and f in ("target_table", "source_table")]
    # 仍然系统级缺失（连接不存在）直接失败转人工
    hard = [f for f in updated["missing"] if f in ("source", "target_conn")]
    if hard:
        return {
            "intent": updated,
            "status": "failed",
            "error": "；".join(_question_for(f, updated) for f in hard),
            "step_trace": ["clarify"],
        }
    return {"intent": updated, "status": "running", "step_trace": ["clarify"]}


async def probe_metadata(state: StudioState) -> dict:
    """元数据探查：复用连接器 profile（只读），产出 profiles。"""
    from app.core.db import session_factory
    from app.core.secret_provider import resolve_config
    from app.domain.connectors.base import CONNECTOR_REGISTRY

    intent = state["intent"] or {}
    assert session_factory is not None
    profiles: dict[str, Any] = {}
    async with session_factory() as db:
        # 1. 源探查（mysql 表或 CSV 文件资产）；表名净化：LLM 可能带库名前缀
        if intent.get("source_conn_id"):
            conn = (await db.execute(select(Connection).where(Connection.id == intent["source_conn_id"]))).scalar_one()
            table = (intent.get("source_table") or "").rsplit(".", 1)[-1].strip("`\" ")
            intent["source_table"] = table  # 净化结果回写（worker 按此建查询）
            result = await CONNECTOR_REGISTRY["mysql"].profile(
                resolve_config(conn.config_json), table, 50
            )
            profiles["source"] = {
                "kind": "mysql",
                "connection_id": conn.id,
                "connection_name": conn.name,
                "table": table,
                "schema": result.schema,
                "stats": result.stats,
            }
        elif intent.get("file_asset_id"):
            asset = (await db.execute(select(FileAsset).where(FileAsset.id == intent["file_asset_id"]))).scalar_one()
            profiles["source"] = {
                "kind": "csv",
                "file_asset_id": asset.id,
                "file_name": asset.file_name,
                "file_path": asset.file_path,
                "schema": asset.schema_json or {"columns": []},
            }
        # 2. 目标连接登记
        if intent.get("target_conn_id"):
            conn = (await db.execute(select(Connection).where(Connection.id == intent["target_conn_id"]))).scalar_one()
            profiles["target"] = {"connection_id": conn.id, "connection_name": conn.name, "table": intent.get("target_table")}
    return {"profiles": profiles, "intent": intent, "step_trace": ["probe_metadata"]}


class EtlPlanDraft(BaseModel):
    """LLM 生成的 EtlPlan 骨架（数值不可信，服务端合并 profile 后定型）。"""

    column_mapping: list[dict] = Field(default_factory=list)
    quality_rules: list[dict] = Field(default_factory=list, description="算子见 INTENT_SYSTEM")
    masking: list[dict] = Field(default_factory=list)


GEN_SYSTEM = (
    "你是 ETL 管道设计师。基于源表结构与用户需求，产出列映射与质量契约。只输出 JSON。"
    "column_mapping: [{source, target}]（同名可直通）；quality_rules: [{column, operator, error_code}]；"
    "masking: [{column, operator}]（仅敏感字段）。error_code 形如 E_NOT_NULL/E_NOT_POSITIVE/E_BAD_EMAIL。"
    "列名必须来自源表结构，禁止编造。"
)


async def generate(state: StudioState) -> dict:
    """生成 EtlPlan + HOCON：LLM 产出契约骨架，服务端与 profile 合并定型。"""
    intent = state["intent"] or {}
    profiles = state.get("profiles", {})
    src_schema = profiles.get("source", {}).get("schema", {})
    columns = [c["name"] for c in src_schema.get("columns", [])]
    # 1. LLM 生成骨架
    draft = await chat(
        [
            {"role": "system", "content": GEN_SYSTEM},
            {"role": "user", "content": json.dumps(
                {"需求": state["prompt"], "源表结构": src_schema, "目标表": intent.get("target_table"),
                 "用户质量要求": intent.get("quality_requirements")},
                ensure_ascii=False)},
        ],
        schema=EtlPlanDraft,
    )
    # 2. 服务端定型：列映射按源列过滤（防 LLM 编造列名）；规则列校验
    valid = set(columns)
    mapping = [m for m in draft.column_mapping if m.get("source") in valid]
    if not mapping:  # 全量直通兜底
        mapping = [{"source": c, "target": c} for c in columns]
    rules = [r for r in draft.quality_rules if r.get("column") in valid]
    # 用户显式要求优先补齐（如 "amount 必须为正数"）
    have = {(r.get("column"), r.get("operator")) for r in rules}
    for q in intent.get("quality_requirements", []):
        if (q.get("column"), q.get("operator")) not in have and q.get("column") in valid:
            rules.append(q)
    masking = [m for m in draft.masking if m.get("column") in valid]
    # 3. EtlPlan 定型（quality_contract 结构与编译器对齐）
    contract = {
        "table": intent.get("target_table"),
        "columns": [m["target"] for m in mapping],
        "rules": rules,
        "masking": masking,
    }
    etl_plan = {
        "source": {
            "kind": profiles.get("source", {}).get("kind"),
            "connection_id": intent.get("source_conn_id"),
            "table": intent.get("source_table"),
            "file_asset_id": intent.get("file_asset_id"),
        },
        "target": {"connection_id": intent.get("target_conn_id"), "table": intent.get("target_table")},
        "mappings": mapping,
        "quality_contract": contract,
        "data_classification": intent.get("data_classification", "internal"),
    }
    # 4. HOCON 形态记录（真实作业体由 worker 按契约构建 JSON，HANDOVER §4.1）
    hocon = json.dumps(
        {
            "env": {"job.mode": "BATCH", "parallelism": 1},
            "source_hint": profiles.get("source", {}).get("kind"),
            "target_table": intent.get("target_table"),
        },
        ensure_ascii=False,
    )
    return {"etl_plan": etl_plan, "hocon": hocon, "step_trace": ["generate"]}


async def gate(state: StudioState) -> dict:
    """确定性门禁（SPEC 5.3）：纯函数四类校验，不调 LLM。"""
    findings: list[GateFinding] = []
    plan = state.get("etl_plan") or {}
    contract = plan.get("quality_contract", {})
    profiles = state.get("profiles", {})
    # 1. hocon/结构存在性
    if not state.get("hocon"):
        findings.append({"rule": "hocon_compile", "level": "blocking", "message": "缺少 HOCON 配置"})
    # 2. schema 对齐：映射列必须在源结构内
    src_cols = {c["name"] for c in profiles.get("source", {}).get("schema", {}).get("columns", [])}
    for m in plan.get("mappings", []):
        if m["source"] not in src_cols:
            findings.append({"rule": "schema_alignment", "level": "blocking",
                             "message": f"源列不存在: {m['source']}"})
    # 3. 契约编译：SQL 形态与算子合法性（编译通过 = 形态合法）
    try:
        compile_contract(contract)
    except ContractCompileError as exc:
        findings.append({"rule": "contract_compile", "level": "blocking", "message": str(exc)})
    # 4. scope_guard：源类型必须是 mysql/csv（D1），目标必须是 doris
    src_kind = profiles.get("source", {}).get("kind")
    if src_kind not in ("mysql", "csv"):
        findings.append({"rule": "scope_guard", "level": "blocking",
                         "message": f"不允许搬运的源类型: {src_kind}（D1）"})
    tgt_conn = plan.get("target", {}).get("connection_id")
    if not tgt_conn:
        findings.append({"rule": "scope_guard", "level": "blocking", "message": "缺少 Doris 目标连接"})
    report: GateReport = {
        "passed": not any(f["level"] == "blocking" for f in findings),
        "findings": findings,
    }
    return {"gate_report": report, "step_trace": ["gate"]}


async def repair(state: StudioState) -> dict:
    """有限自动修复：repair_round 内重建契约（确定性去重/裁剪），超限转人工。

    ponytail: 修复策略为确定性规则（剔除非法列/算子）而非 LLM 重生成——
    门禁失败原因全部来自 LLM 编造列名，裁剪即可修复，无需再调 LLM。
    """
    from app.core.config import get_settings

    max_rounds = get_settings().gate_max_repair_rounds
    round_no = state.get("repair_round", 0) + 1
    if round_no > max_rounds:
        return {"status": "failed", "error": "自动修复超限，转人工处理", "step_trace": [f"repair_exhausted({max_rounds})"]}
    plan = state.get("etl_plan") or {}
    profiles = state.get("profiles", {})
    src_cols = {c["name"] for c in profiles.get("source", {}).get("schema", {}).get("columns", [])}
    # 1. 剔除非法映射与规则列
    plan["mappings"] = [m for m in plan.get("mappings", []) if m["source"] in src_cols]
    contract = plan.get("quality_contract", {})
    contract["rules"] = [r for r in contract.get("rules", []) if r.get("column") in src_cols]
    contract["masking"] = [m for m in contract.get("masking", []) if m.get("column") in src_cols]
    contract["columns"] = [m["target"] for m in plan["mappings"]]
    # 2. 修复后落回计划再复检
    return {"etl_plan": plan, "repair_round": round_no, "step_trace": [f"repair_round_{round_no}"]}
