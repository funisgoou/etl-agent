"""Celery 应用装配：Redis Broker；beat 周期任务（准备单过期清理）。"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

celery_app = Celery(
    "etl_agent",
    broker=get_settings().redis_url,
    backend=get_settings().redis_url,
    include=["app.worker.tasks", "app.worker.beat_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    beat_schedule={
        # 准备单 TTL 过期清理（DATA 3.4）
        "expire-preparations": {
            "task": "app.worker.beat_tasks.expire_preparations",
            "schedule": crontab(minute="*/15"),
        },
    },
)
