"""连接器扩展点（SPEC 3.3）：新增数据源实现 Connector，不动内核。

v1 行为约束（D1）：仅 mysql/doris 可进入搬运链路；其余 profile-only。
探查一律只读（SELECT/信息 Schema，禁止写与 DDL）。
"""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import aiomysql


@dataclass(slots=True)
class TestResult:
    """连通性测试结果。"""

    ok: bool
    latency_ms: int = 0
    server_version: str = ""
    message: str = ""


@dataclass(slots=True)
class ProfileResult:
    """探查结果：结构 + 统计 + 脱敏前样本（入库前再统一脱敏）。"""

    schema: dict  # {"columns": [{"name","type","nullable"}], "primary_key": [...]}
    stats: dict = field(default_factory=dict)  # {"approx_rows": int}
    sample: list[dict] = field(default_factory=list)


@runtime_checkable
class Connector(Protocol):
    """连接器协议：test/list_objects/profile 三个能力。"""

    conn_type: str
    portable: bool  # 是否允许进入搬运链路（D1）

    async def test(self, config: dict) -> TestResult: ...

    async def list_objects(self, config: dict) -> list[str]: ...

    async def profile(self, config: dict, object_name: str, sample_size: int) -> ProfileResult: ...


async def _mysql_query(config: dict, sql: str, args: tuple = ()) -> list[tuple]:
    """MySQL 协议通用只读查询（mysql/doris 共用，aiomysql）。"""
    import time

    conn = await aiomysql.connect(
        host=config["host"],
        port=int(config.get("port", 3306)),
        user=config["username"],
        password=config.get("password", ""),
        db=config.get("database", ""),
        connect_timeout=5,
    )
    try:
        cur = await conn.cursor()
        await cur.execute(sql, args)
        return await cur.fetchall()
    finally:
        conn.close()


class MysqlConnector:
    """MySQL 连接器（可搬运源端）。"""

    conn_type = "mysql"
    portable = True

    async def test(self, config: dict) -> TestResult:
        import time

        t0 = time.monotonic()
        try:
            rows = await _mysql_query(config, "SELECT VERSION()")
            return TestResult(ok=True, latency_ms=int((time.monotonic() - t0) * 1000), server_version=rows[0][0])
        except Exception as exc:
            return TestResult(ok=False, message=str(exc))

    async def list_objects(self, config: dict) -> list[str]:
        rows = await _mysql_query(config, "SHOW TABLES")
        return [r[0] for r in rows]

    async def profile(self, config: dict, object_name: str, sample_size: int) -> ProfileResult:
        # 1. 只读护栏：表名白名单校验（防注入）
        import re

        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", object_name):
            raise ValueError(f"非法表名: {object_name}")
        # 2. 结构（information_schema）
        cols_rows = await _mysql_query(
            config,
            "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_KEY FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION",
            (config.get("database", ""), object_name),
        )
        columns = [
            {"name": r[0], "type": r[1], "nullable": r[2] == "YES", "key": r[3]}
            for r in cols_rows
        ]
        pk = [r[0] for r in cols_rows if r[3] == "PRI"]
        # 3. 近似统计
        cnt = await _mysql_query(config, f"SELECT COUNT(*) FROM `{object_name}`")
        # 4. 样本（LIMIT 硬约束）
        sample_rows = await _mysql_query(config, f"SELECT * FROM `{object_name}` LIMIT %s", (sample_size,))
        names = [c["name"] for c in columns]
        sample = [dict(zip(names, row)) for row in sample_rows]
        return ProfileResult(
            schema={"columns": columns, "primary_key": pk},
            stats={"approx_rows": cnt[0][0]},
            sample=sample,
        )


class DorisConnector(MysqlConnector):
    """Doris 连接器（MySQL 协议，可搬运目标端）。"""

    conn_type = "doris"
    portable = True


class PostgresqlConnector:
    """PostgreSQL 连接器（仅登记与探查，D1）。"""

    conn_type = "postgresql"
    portable = False

    async def test(self, config: dict) -> TestResult:
        import asyncpg

        try:
            conn = await asyncpg.connect(
                host=config["host"], port=int(config.get("port", 5432)),
                user=config["username"], password=config.get("password", ""),
                database=config.get("database", ""), timeout=5,
            )
            ver = await conn.fetchval("SELECT version()")
            await conn.close()
            return TestResult(ok=True, server_version=ver.split(",")[0] if ver else "")
        except Exception as exc:
            return TestResult(ok=False, message=str(exc))

    async def list_objects(self, config: dict) -> list[str]:
        import asyncpg

        conn = await asyncpg.connect(
            host=config["host"], port=int(config.get("port", 5432)),
            user=config["username"], password=config.get("password", ""),
            database=config.get("database", ""), timeout=5,
        )
        rows = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        await conn.close()
        return [r["tablename"] for r in rows]

    async def profile(self, config: dict, object_name: str, sample_size: int) -> ProfileResult:
        import asyncpg

        conn = await asyncpg.connect(
            host=config["host"], port=int(config.get("port", 5432)),
            user=config["username"], password=config.get("password", ""),
            database=config.get("database", ""), timeout=5,
        )
        cols = await conn.fetch(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=$1 ORDER BY ordinal_position",
            object_name,
        )
        cnt = await conn.fetchval(f'SELECT COUNT(*) FROM "{object_name}"')
        rows = await conn.fetch(f'SELECT * FROM "{object_name}" LIMIT {int(sample_size)}')
        await conn.close()
        return ProfileResult(
            schema={"columns": [
                {"name": c["column_name"], "type": c["data_type"], "nullable": c["is_nullable"] == "YES"}
                for c in cols
            ], "primary_key": []},
            stats={"approx_rows": cnt},
            sample=[dict(r) for r in rows],
        )


# 注册表：新增连接器在此登记（扩展点）；csv 不注册——文件资产走 file_assets 通道（D8/C3）
CONNECTOR_REGISTRY: dict[str, Connector] = {
    "mysql": MysqlConnector(),
    "doris": DorisConnector(),
    "postgresql": PostgresqlConnector(),
    # oracle/clickhouse/s3/rest_api：登记占位（连接类型合法，探查能力二期接入）
}
REGISTERED_TYPES = ("mysql", "postgresql", "oracle", "doris", "clickhouse", "s3", "rest_api")
