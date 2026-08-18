"""ToolIntent 定义（SPEC 4.1）：所有副作用的意图载体。

harness 不 import domain（内核可独立演进）。
"""

from dataclasses import dataclass

# 已注册的工具意图（扩展点：新增工具在此扩充）
TOOL_INTENTS = ("execute_pipeline", "dry_run", "rollback", "cleanup", "cancel")


@dataclass(frozen=True, slots=True)
class ToolIntent:
    """工具意图：一次受管副作用的完整描述。

    Attributes:
        tool: 工具名（execute_pipeline/dry_run/rollback/cleanup/cancel）。
        version_id: 目标 Pipeline 版本。
        project_id: 项目边界（账本归属）。
        subject_id: 发起主体（user_id）。
        resource_scope: 资源范围（连接/库表/文件）。
        data_classification: 数据分级 public/internal/confidential/secret。
        params: 附加参数。
    """

    tool: str
    version_id: int
    project_id: int
    subject_id: int
    resource_scope: dict
    data_classification: str
    params: dict
