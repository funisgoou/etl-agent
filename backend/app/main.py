"""FastAPI 装配：lifespan 资源管理 + 路由注册 + 全局异常处理。"""

import asyncio
import sys
from contextlib import asynccontextmanager

# Windows 宿主直跑时 psycopg（PostgresSaver）需 Selector 循环；Linux 容器内默认即兼容
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core import db, redis_client
from app.core.errors import install_exception_handlers
from app.core.logging import new_trace_id, setup_logging

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """资源生命周期：引擎/Redis init ↔ dispose。"""
    setup_logging()
    db.init_engine()
    redis_client.init_redis()
    logger.info("etl-agent 控制面启动")
    yield
    await db.dispose_engine()
    await redis_client.dispose_redis()


def create_app() -> FastAPI:
    """应用工厂。"""
    app = FastAPI(title="ETL-Agent 数据集成平台", version="1.0.0", lifespan=lifespan)
    install_exception_handlers(app)

    # TraceID 中间件：每请求生成并注入日志上下文
    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        new_trace_id()
        return await call_next(request)

    # 2. 路由注册
    from app.domain import (audit, auth, benchmark, connections, evolution,
                            executions, file_assets, pipelines, preparations,
                            projects, studio)

    app.include_router(auth.router)
    app.include_router(projects.router)
    app.include_router(connections.router)
    app.include_router(file_assets.router)
    app.include_router(pipelines.router)
    app.include_router(studio.router)
    app.include_router(preparations.router)
    app.include_router(executions.router)
    app.include_router(benchmark.router)
    app.include_router(audit.router)
    app.include_router(evolution.router)

    # 3. 健康检查（无认证，API 2）
    from app.core.config import get_settings

    @app.get("/health")
    async def health() -> JSONResponse:
        """依赖就绪检查：postgres/redis 硬依赖，数据面组件按配置探测。"""
        import httpx

        components: dict[str, str] = {}
        degraded = False
        # 3a. postgres
        try:
            from sqlalchemy import text

            assert db.session_factory is not None
            async with db.session_factory() as s:
                await s.execute(text("SELECT 1"))
            components["postgres"] = "ok"
        except Exception as exc:  # noqa: BLE001
            components["postgres"] = f"error: {exc}"
            degraded = True
        # 3b. redis
        try:
            await redis_client.redis_client().ping()
            components["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001
            components["redis"] = f"error: {exc}"
            degraded = True
        # 3c. 数据面（尽力而为，不计入 degraded——数据面独立 profile）
        # SeaTunnel 2.3.12 无 /hazelcast/rest/health 端点（空回复）；用作业列表接口作活性探测
        s = get_settings()
        for name, url in (("seatunnel", f"{s.seatunnel_url}/hazelcast/rest/maps/finished-jobs"),):
            try:
                async with httpx.AsyncClient(timeout=2) as c:
                    r = await c.get(url)
                    components[name] = "ok" if r.status_code < 500 else f"http {r.status_code}"
            except Exception:  # noqa: BLE001
                components[name] = "unreachable"
        return JSONResponse(
            status_code=503 if degraded else 200,
            content={"status": "degraded" if degraded else "ok", "components": components},
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
