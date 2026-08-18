"""uvicorn 启动入口。

Windows 宿主直跑必须用本入口（python run.py）：SelectorEventLoop 策略必须在
uvicorn 创建事件循环之前设置（main.py 模块级设置在 uvicorn CLI 场景下时机太晚，
PostgresSaver/psycopg 会报 ProactorEventLoop 错误）。Linux 容器内无此约束。
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
