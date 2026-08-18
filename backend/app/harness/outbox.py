"""Transactional Outbox（SPEC 4.5）：事件与业务事实同事务落库 + 后台中继。"""

import json
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_model import OutboxEvent

logger = structlog.get_logger(__name__)


async def emit(
    session: AsyncSession,
    aggregate_type: str,
    aggregate_id: int,
    event_type: str,
    payload: dict,
) -> OutboxEvent:
    """写入 Outbox 事件（必须在业务事务内调用）。"""
    row = OutboxEvent(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload_json=payload,
    )
    session.add(row)
    await session.flush()
    return row


async def fetch_pending(session: AsyncSession, limit: int = 10) -> list[OutboxEvent]:
    """捞取待投递事件（Worker/中继轮询）。"""
    rows = (
        (
            await session.execute(
                select(OutboxEvent)
                .where(OutboxEvent.status == "pending")
                .order_by(OutboxEvent.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def mark_published(session: AsyncSession, event_id: int) -> None:
    """投递成功置 published。"""
    await session.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id == event_id)
        .values(status="published", published_at=datetime.now(UTC))
    )


async def mark_failed(session: AsyncSession, event_id: int) -> None:
    """投递失败置 failed（中继会按退避重试 pending）。"""
    await session.execute(
        update(OutboxEvent).where(OutboxEvent.id == event_id).values(status="failed")
    )


def payload_json_str(payload: dict) -> str:
    """载荷序列化辅助（Celery 参数只传 JSON 串）。"""
    return json.dumps(payload, ensure_ascii=False, default=str)
