"""Beat 周期任务：准备单 TTL 过期置 expired + 账本留痕。"""

import asyncio
from datetime import UTC, datetime

import structlog
from celery import shared_task
from sqlalchemy import select, update

logger = structlog.get_logger(__name__)


async def _expire() -> int:
    from app.core.db import make_session_factory
    from app.db_model import ApprovalRequest, Preparation
    from app.harness.ledger import append

    factory = make_session_factory()
    async with factory() as db:
        async with db.begin():
            # 1. 过期未终结单
            rows = (await db.execute(
                select(Preparation).where(
                    Preparation.status.in_(("pending", "approved")),
                    Preparation.expires_at < datetime.now(UTC),
                )
            )).scalars().all()
            for p in rows:
                p.status = "expired"
                await db.execute(
                    update(ApprovalRequest)
                    .where(ApprovalRequest.preparation_id == p.id, ApprovalRequest.status == "pending")
                    .values(status="cancelled")
                )
                await append(db, p.version_id, 0, "prepare_expired", "preparation", p.id, {})
            return len(rows)


@shared_task(name="app.worker.beat_tasks.expire_preparations")
def expire_preparations() -> str:
    n = asyncio.run(_expire())
    if n:
        logger.info("准备单过期清理", count=n)
    return f"expired:{n}"
