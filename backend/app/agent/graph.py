"""LangGraph 图定义：意图 → 澄清 → 探查 → 生成 → 门禁 →（修复|完成）。

PostgresSaver checkpoint 为恢复唯一真相源（D10）；
agent_runs 表由 studio 域写投影。
"""

import uuid
from typing import Literal

import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.agent import nodes
from app.agent.state import StudioState

logger = structlog.get_logger(__name__)

_compiled = None  # 编译缓存（图无状态可复用；checkpointer 每次用连接串新建）


def new_thread_id(version_id: int) -> str:
    """thread_id 绑定 version_id（D10）。"""
    return f"v{version_id}-{uuid.uuid4().hex[:12]}"


def need_clarify(state: StudioState) -> Literal["clarify", "probe"]:
    """路由：缺参 → 澄清；否则直接探查。"""
    missing = (state.get("intent") or {}).get("missing", [])
    # 系统级缺失（连接不存在）也走 clarify 统一报错
    return "clarify" if missing else "probe"


def gate_route(state: StudioState) -> Literal["repair", "end_ok"]:
    """路由：门禁通过 → 结束；失败且可修复 → repair；失败且超限 → 结束（failed 由 repair 节点置位）。"""
    report = state.get("gate_report") or {}
    if report.get("passed"):
        return "end_ok"
    if state.get("status") == "failed":
        return "end_ok"  # 修复超限，repair 已置 failed
    return "repair"


def build_graph():
    """构建并编译状态图。"""
    g = StateGraph(StudioState)
    g.add_node("parse_intent", nodes.parse_intent)
    g.add_node("clarify", nodes.clarify)
    g.add_node("probe", nodes.probe_metadata)
    g.add_node("generate", nodes.generate)
    g.add_node("gate", nodes.gate)
    g.add_node("repair", nodes.repair)
    g.add_edge(START, "parse_intent")
    g.add_conditional_edges("parse_intent", need_clarify, {"clarify": "clarify", "probe": "probe"})
    g.add_conditional_edges(
        "clarify",
        lambda s: "probe" if s.get("status") != "failed" else END,
        {"probe": "probe", END: END},
    )
    g.add_edge("probe", "generate")
    g.add_edge("generate", "gate")
    g.add_conditional_edges("gate", gate_route, {"repair": "repair", "end_ok": END})
    g.add_edge("repair", "gate")
    return g.compile()


def get_graph():
    """编译缓存。"""
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled


def get_checkpointer():
    """PostgresSaver 工厂：每调用方自管生命周期（async with）。"""
    from app.core.config import get_settings

    return AsyncPostgresSaver.from_conn_string(get_settings().database_url)
