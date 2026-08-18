"""LangGraph Workflow State（SPEC 5.1）。

thread_id 绑定 version_id（D10）；agent_runs 表仅投影。
"""

from typing import Annotated, Any, Literal, TypedDict

import operator


class IntentSpec(TypedDict, total=False):
    """意图解析产物：源/目标/表/映射/质量要求的结构化抽取。"""

    source_conn_id: int | None        # MySQL 源连接
    source_table: str | None
    file_asset_id: int | None         # CSV 源（file_assets 通道，D8）
    target_conn_id: int | None        # Doris 目标连接
    target_table: str | None
    column_mapping: list[dict]        # [{source, target, transform?}]
    quality_requirements: list[dict]  # [{column, operator, error_code?}]（自然语言）
    data_classification: str          # public/internal/confidential/secret
    missing: list[str]                # 缺参字段名


class QA(TypedDict):
    """一轮澄清问答。"""

    field: str
    question: str
    answer: Any


class GateFinding(TypedDict):
    rule: str
    level: Literal["blocking", "warning"]
    message: str


class GateReport(TypedDict):
    passed: bool
    findings: list[GateFinding]


class StudioState(TypedDict, total=False):
    """状态机全量状态（checkpoint 持久化与恢复的唯一载体）。"""

    version_id: int
    project_id: int
    thread_id: str
    prompt: str
    intent: IntentSpec | None
    clarifications: Annotated[list[QA], operator.add]
    profiles: dict[str, Any]          # {"source": {...}, "target": {...}}
    etl_plan: dict | None             # EtlPlan（含 quality_contract）
    hocon: str | None                 # SeaTunnel HOCON（演示形态，实际作业体为 JSON）
    gate_report: GateReport | None
    repair_round: int
    status: Literal["running", "waiting_input", "gated", "failed", "succeeded"]
    error: str | None
    step_trace: Annotated[list[str], operator.add]  # 节点推进轨迹（前端时间线）
