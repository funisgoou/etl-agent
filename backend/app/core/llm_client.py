"""LLM 客户端（SPEC 2.6 / D6）：OpenAI 兼容协议封装。

模型名与端点全部来自 Settings，代码不硬编码（D6）。
LLM 产出的所有数值按不可信输入处理，由调用方兜底（纪律 #8）。
"""

import json
from typing import TypeVar

import structlog
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.core.config import get_settings

logger = structlog.get_logger(__name__)
T = TypeVar("T", bound=BaseModel)

_client: AsyncOpenAI | None = None


def llm_client() -> AsyncOpenAI:
    """客户端单例。"""
    global _client
    if _client is None:
        s = get_settings()
        _client = AsyncOpenAI(
            base_url=s.llm_base_url, api_key=s.llm_api_key, timeout=s.llm_timeout_seconds
        )
    return _client


async def chat(messages: list[dict], *, schema: type[T] | None = None) -> "str | T":
    """对话补全；schema 提供时强制 JSON 输出并解析校验（不可信输入兜底默认值由 schema 默认值承担）。"""
    s = get_settings()
    kwargs: dict = {
        "model": s.llm_model_id,
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"} if schema else None,
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    resp = await llm_client().chat.completions.create(**kwargs)
    text = resp.choices[0].message.content or ""
    if schema is None:
        return text
    # 1. 剥离可能的 markdown 代码块围栏
    stripped = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    # 2. 解析为 Pydantic 模型（校验失败抛出，由调用方走修复/失败分支）
    try:
        return schema.model_validate_json(stripped)
    except Exception:
        first, last = stripped.find("{"), stripped.rfind("}")
        if first >= 0 and last > first:
            return schema.model_validate_json(stripped[first : last + 1])
        raise


def parse_json_loose(text: str) -> dict:
    """宽松解析 LLM 裸 JSON 文本（辅助）。"""
    stripped = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(stripped)
