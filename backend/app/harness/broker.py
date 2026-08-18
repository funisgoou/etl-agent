"""Tool Broker（SPEC 4.4）：所有外部副作用的唯一出口。

execute()：验签消费 → intent/claims 一致性校验 → 调用 handler → 写账本（成功/失败均写）。
Worker 侧消费 Outbox 命令时复用 verify_and_consume 完成同等校验。
"""

from collections.abc import Awaitable, Callable
from typing import TypeVar

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.harness import capability
from app.harness.capability import CapabilityClaims
from app.harness.intents import ToolIntent
from app.harness.ledger import append

logger = structlog.get_logger(__name__)
T = TypeVar("T")


async def execute(
    session: AsyncSession,
    intent: ToolIntent,
    token: str,
    artifact_digest: str,
    handler: Callable[[CapabilityClaims], Awaitable[T]],
) -> T:
    """受管副作用执行：验签 → 一致性 → handler → 账本。

    Args:
        session: 数据库会话（调用方持有事务）。
        intent: 工具意图。
        token: Capability 明文令牌。
        artifact_digest: 期望绑定的制品指纹（None 跳过比对）。
        handler: 实际副作用封装（Worker 任务入口）。

    Raises:
        ApiError: 令牌非法/重放/越权（E_TOKEN_*）。
    """
    # 1. 验签消费（Replay Guard 在同一事务内原子置位）
    claims = await capability.verify_and_consume(session, token, intent.tool, artifact_digest)
    # 2. 主体绑定校验
    if claims.subject_id != intent.subject_id:
        from app.core.errors import ApiError

        raise ApiError("E_TOKEN_SCOPE", "令牌主体与意图发起人不符")
    # 3. 执行 handler（异常也进账本后向上抛）
    try:
        result = await handler(claims)
    except Exception as exc:
        await append(
            session,
            project_id=intent.project_id,
            actor_id=intent.subject_id,
            event_type=f"{intent.tool}_failed",
            resource_type="execution",
            resource_id=intent.params.get("execution_run_id", intent.version_id),
            payload={"error": str(exc), "tool": intent.tool},
        )
        raise
    # 4. 成功账本
    await append(
        session,
        project_id=intent.project_id,
        actor_id=intent.subject_id,
        event_type=f"{intent.tool}_executed",
        resource_type="execution",
        resource_id=intent.params.get("execution_run_id", intent.version_id),
        payload={"tool": intent.tool, "version_id": intent.version_id},
    )
    return result
