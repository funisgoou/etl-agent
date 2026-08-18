"""Outbox 中继（SPEC 4.5 relay_loop）：pending → 投递 Celery → published。

部署形态：API 容器内随主进程常驻（compose api command 里 python -m app.worker.relay）。
"""

import asyncio
import json

import structlog

from app.core.db import init_engine, dispose_engine, make_session_factory
from app.core.logging import setup_logging
from app.harness import outbox

logger = structlog.get_logger(__name__)

# event_type → Celery 任务名
_TASK_ROUTES = {
    "execute_pipeline": "app.worker.tasks.execute_pipeline",
    "dry_run": "app.worker.tasks.execute_pipeline",
    "cancel_run": "app.worker.tasks.cancel_run",
    "rollback": "app.worker.tasks.rollback",
}


async def relay_once() -> int:
    """捞一批 pending 事件投递 Celery。"""
    factory = make_session_factory()
    delivered = 0
    async with factory() as db:
        async with db.begin():
            events = await outbox.fetch_pending(db, limit=10)
            for ev in events:
                task = _TASK_ROUTES.get(ev.event_type)
                if task is None:
                    await outbox.mark_failed(db, ev.id)
                    continue
                try:
                    # 1. 投递 Celery（JSON 载荷）
                    from app.worker.celery_app import celery_app

                    celery_app.send_task(task, args=[json.dumps({**ev.payload_json, 'event_type': ev.event_type}, ensure_ascii=False, default=str)])
                    # 2. 置 published
                    await outbox.mark_published(db, ev.id)
                    delivered += 1
                except Exception as exc:  # noqa: BLE001
                    logger.error(f"outbox 投递失败:{exc}", event_id=ev.id)
                    await outbox.mark_failed(db, ev.id)
    return delivered


async def relay_loop(interval: float = 2.0) -> None:
    """常驻循环。"""
    setup_logging()
    init_engine()
    logger.info("outbox relay 启动")
    try:
        while True:
            try:
                await relay_once()
            except Exception as exc:  # noqa: BLE001
                logger.error(f"relay 轮次异常:{exc}")
            await asyncio.sleep(interval)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(relay_loop())
