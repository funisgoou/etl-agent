"""结构化日志（纪律 #11）：structlog + 请求级 TraceID。"""

import contextvars
import uuid

import structlog

# 请求级 trace_id（中间件写入，日志统一带出）
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")


def new_trace_id() -> str:
    """生成并绑定新 trace_id，返回本体。"""
    tid = uuid.uuid4().hex
    trace_id_var.set(tid)
    return tid


def setup_logging() -> None:
    """配置 structlog：JSON 输出 + trace_id 注入。"""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            lambda _, __, ed: {**ed, "trace_id": trace_id_var.get()},
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO+
        cache_logger_on_first_use=True,
    )
