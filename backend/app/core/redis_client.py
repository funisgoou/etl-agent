"""Redis 客户端（SPEC 2.8）：连接单例 + 运行状态 pub/sub（D7 SSE 回传通道）。

Redis 不承担防重放/nonce 存证（D2）。
"""

import json
from typing import Any

import redis.asyncio as aioredis

from app.core.config import get_settings

# 模块级单例（init/dispose 模式）
_client: aioredis.Redis | None = None


def init_redis() -> None:
    """初始化连接池单例。"""
    global _client
    _client = aioredis.from_url(get_settings().redis_url, decode_responses=True)


async def dispose_redis() -> None:
    """关闭连接池。"""
    if _client is not None:
        await _client.aclose()
        _client = None


def redis_client() -> aioredis.Redis:
    """取连接（须先 init_redis）。"""
    assert _client is not None, "redis 未初始化"
    return _client


def publish_status(run_id: int, event: dict[str, Any]) -> None:
    """Worker 回传运行状态到 exec_run:{id} 频道（fire-and-forget，SSE 只做通知）。"""
    if _client is None:
        return
    _client.publish(f"exec_run:{run_id}", json.dumps(event, ensure_ascii=False, default=str))
