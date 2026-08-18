"""数据库基础设施（SPEC 2.2）：SQLAlchemy 2.x 异步引擎、会话与事务工具。

可变全局资源走 init/dispose 模式：lifespan 中 init，其他模块导入本模块（非成员）。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (AsyncEngine, AsyncSession,
                                    async_sessionmaker, create_async_engine)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


class Base(DeclarativeBase):
    """声明式基类：全部 ORM 模型继承于此。"""


# 模块级可变单例（导入模块而非成员使用）
engine: AsyncEngine | None = None
session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine() -> None:
    """初始化全局异步引擎与会话工厂（FastAPI lifespan / 长驻进程调用）。"""
    global engine, session_factory
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def dispose_engine() -> None:
    """释放引擎连接池。"""
    if engine is not None:
        await engine.dispose()


def make_session_factory() -> async_sessionmaker[AsyncSession]:
    """为独立事件循环（Celery 任务内 asyncio.run）创建一次性会话工厂。

    asyncpg 连接池绑定事件循环，跨循环复用会报 "attached to a different loop"，
    因此 Worker 每个任务用独立工厂 + NullPool。
    """
    eng = create_async_engine(get_settings().database_url, poolclass=NullPool)
    return async_sessionmaker(eng, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI Depends 会话：请求级生命周期，自动提交/回滚。"""
    assert session_factory is not None, "db engine 未初始化（init_engine）"
    async with session_factory() as session:
        yield session


@asynccontextmanager
async def atomic() -> AsyncIterator[AsyncSession]:
    """显式事务块：Commit 三阶段 / Outbox 等需要精细控制事务的场景使用。"""
    assert session_factory is not None, "db engine 未初始化（init_engine）"
    async with session_factory() as session:
        async with session.begin():
            yield session
