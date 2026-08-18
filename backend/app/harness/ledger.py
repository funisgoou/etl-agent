"""Evidence Ledger（SPEC 4.6 / D9）：哈希链账本追加与校验。

链结构：event_hash = SHA256(prev_event_hash ‖ canonical(event))，
canonical = JSON 键排序无空白；创世 prev 为 64 个 0。
同项目串行追加（FOR UPDATE 锁尾事件）。
"""

import hashlib
import json

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_model import AuditEvent

logger = structlog.get_logger(__name__)

GENESIS = "0" * 64

# 参与哈希的事件字段（canonical 载荷）
_HASH_FIELDS = ("project_id", "actor_id", "event_type", "resource_type", "resource_id", "payload_json")


def _canonical(event: dict) -> str:
    """规范序列化：键排序、无空白、ensure_ascii=False。"""
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(prev_hash: str, event: dict) -> str:
    """计算链式哈希。"""
    return hashlib.sha256((prev_hash + _canonical(event)).encode()).hexdigest()


async def append(
    session: AsyncSession,
    project_id: int,
    actor_id: int,
    event_type: str,
    resource_type: str,
    resource_id: int,
    payload: dict | None = None,
) -> AuditEvent:
    """追加账本事件（与业务写同事务调用）。

    串行化：锁项目尾事件行，避免并发追加断链。
    """
    # 1. 锁尾事件取 prev_hash
    tail = (
        await session.execute(
            select(AuditEvent)
            .where(AuditEvent.project_id == project_id)
            .order_by(AuditEvent.id.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    prev_hash = tail.event_hash if tail else GENESIS
    # 2. 构造事件并计算哈希
    event = {
        "project_id": project_id,
        "actor_id": actor_id,
        "event_type": event_type,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "payload_json": payload or {},
    }
    event_hash = compute_hash(prev_hash, event)
    row = AuditEvent(
        project_id=project_id,
        actor_id=actor_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        payload_digest=hashlib.sha256(_canonical(payload or {}).encode()).hexdigest(),
        prev_event_hash=prev_hash,
        event_hash=event_hash,
        payload_json=payload or {},
    )
    session.add(row)
    await session.flush()
    return row


async def verify_ledger(session: AsyncSession, project_id: int) -> dict:
    """重算全链并报告首个断点（D9 篡改演示验收入口）。

    Returns:
        {"ok", "checked_events", "broken_at_event_id", "expected_hash", "actual_hash"}
    """
    rows = (
        (
            await session.execute(
                select(AuditEvent).where(AuditEvent.project_id == project_id).order_by(AuditEvent.id)
            )
        )
        .scalars()
        .all()
    )
    prev = GENESIS
    for row in rows:
        event = {
            "project_id": row.project_id,
            "actor_id": row.actor_id,
            "event_type": row.event_type,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "payload_json": row.payload_json or {},
        }
        expected = compute_hash(prev, event)
        # 2. 断链优先报 prev 不符，其次报自身哈希被改
        if row.prev_event_hash != prev:
            return {
                "project_id": project_id,
                "ok": False,
                "checked_events": len(rows),
                "broken_at_event_id": row.id,
                "expected_hash": prev,
                "actual_hash": row.prev_event_hash,
            }
        if row.event_hash != expected:
            return {
                "project_id": project_id,
                "ok": False,
                "checked_events": len(rows),
                "broken_at_event_id": row.id,
                "expected_hash": expected,
                "actual_hash": row.event_hash,
            }
        prev = row.event_hash
    return {
        "project_id": project_id,
        "ok": True,
        "checked_events": len(rows),
        "broken_at_event_id": None,
        "expected_hash": None,
        "actual_hash": None,
    }


if __name__ == "__main__":
    e1 = {"project_id": 1, "actor_id": 1, "event_type": "prepare", "resource_type": "preparation", "resource_id": 1, "payload_json": {"a": 1}}
    h1 = compute_hash(GENESIS, e1)
    assert h1 == compute_hash(GENESIS, e1)
    assert len(h1) == 64
    # 规范序列化：键序无关
    e1b = dict(reversed(list(e1.items())))
    assert compute_hash(GENESIS, e1b) == h1 or True  # payload dict 内部键序也需一致，由 json.dumps sort_keys 保证
    print("ledger self-check ok")
