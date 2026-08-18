"""Doris MySQL 协议客户端（Worker 专用）：受管 SQL 执行 + 表族生命周期。

五槽位表族（D7）：{t}__raw(TRUNCATE) / __shadow(重建) / __err(追加留7天) / {t}(正式) / {t}__bak(留7天)。
Doris 契约（HANDOVER §4.2）：replication_num=1；swap=true 双向互换；首跑 CREATE LIKE。
"""

import re

import aiomysql
import structlog

from app.core.config import get_settings

logger = structlog.get_logger(__name__)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Doris:
    """Doris 连接封装（每任务新建连接，用完即关）。"""

    def __init__(self, db: str | None = None) -> None:
        s = get_settings()
        self.db = db or s.doris_database
        self._cfg = dict(host=s.doris_host, port=s.doris_port, user=s.doris_user,
                         password=s.doris_password, db=self.db, connect_timeout=10)

    async def _run(self, sql: str, args: tuple = ()) -> list[tuple]:
        """执行 SQL 返回行集。"""
        conn = await aiomysql.connect(**self._cfg)
        try:
            cur = await conn.cursor()
            await cur.execute(sql, args)
            try:
                return await cur.fetchall()
            except aiomysql.err.Error:
                return []
        finally:
            conn.close()

    async def exec(self, sql: str, args: tuple = ()) -> list[tuple]:
        return await self._run(sql, args)

    async def scalar(self, sql: str, args: tuple = ()) -> object:
        rows = await self._run(sql, args)
        return rows[0][0] if rows else None

    # ── 表族生命周期 ──

    async def ensure_table_family(self, table: str, columns_def: str) -> None:
        """确保 raw/shadow/err 三表存在（首次执行时按源结构建表）。

        Args:
            table: 正式表名。
            columns_def: "id BIGINT, name VARCHAR(255)" 形态列定义（编译器/调用方给）。
        """
        self._check(table)
        # 1. 库级确认
        await self._run(f"CREATE DATABASE IF NOT EXISTS `{self.db}`")
        # 2. 三槽位表（replication_num=1 单 BE 契约；__err 仅追加错误码列与 SELECT 对齐）
        for suffix in ("__raw", "__shadow", "__err"):
            t = f"{table}{suffix}"
            extra = ", `__error_code` VARCHAR(32) NULL" if suffix == "__err" else ""
            await self._run(
                f"CREATE TABLE IF NOT EXISTS `{t}` ({columns_def}{extra}) "
                f'DUPLICATE KEY(`id`) PROPERTIES("replication_num"="1")'
            )

    async def truncate_raw(self, table: str) -> None:
        """run 隔离：清空 raw 槽位（幂等重跑基础）。"""
        await self._run(f"TRUNCATE TABLE `{table}__raw`")

    async def rebuild_shadow(self, table: str) -> None:
        """重建 shadow 槽位。"""
        await self._run(f"TRUNCATE TABLE `{table}__shadow`")

    async def ensure_main_table(self, table: str, columns_def: str) -> None:
        """首跑正式表不存在时建同构表（HANDOVER §4.2.3）。"""
        await self._run(
            f"CREATE TABLE IF NOT EXISTS `{table}` ({columns_def}) "
            f'DUPLICATE KEY(`id`) PROPERTIES("replication_num"="1")'
        )

    async def atomic_swap(self, table: str) -> None:
        """原子发布：shadow ↔ 正式表互换（swap=true），旧数据落入 shadow 槽位后改名 __bak。"""
        # 1. 互换（旧正式表数据落回 shadow 槽位）
        await self._run(
            f"ALTER TABLE `{table}` REPLACE WITH TABLE `{table}__shadow` PROPERTIES('swap'='true')"
        )
        # 2. 互换后 shadow 槽位是旧正式数据 → 备份改名 __bak（先清旧备份）
        await self._run(f"DROP TABLE IF EXISTS `{table}__bak`")
        await self._run(f"ALTER TABLE `{table}__shadow` RENAME `{table}__bak`")

    async def rollback_swap(self, table: str) -> None:
        """受管回滚：__bak 与正式表再互换一次（P1 处理，签发 Capability）。"""
        await self._run(
            f"ALTER TABLE `{table}` REPLACE WITH TABLE `{table}__bak` PROPERTIES('swap'='true')"
        )
        await self._run(f"ALTER TABLE `{table}__bak` RENAME `{table}__shadow`")

    async def count(self, table: str) -> int:
        return int(await self.scalar(f"SELECT COUNT(*) FROM `{self._check(table)}`"))

    async def drop_family(self, table: str, database: str | None = None) -> None:
        """Dry-Run 清理：删除临时表族。"""
        for suffix in ("__raw", "__shadow", "__err"):
            try:
                await self._run(f"DROP TABLE IF EXISTS `{table}{suffix}`")
            except Exception as exc:  # noqa: BLE001
                logger.warning("drop_family 忽略错误", table=table, error=str(exc))

    def _check(self, name: str) -> str:
        if not _IDENT.match(name):
            raise ValueError(f"非法表名: {name}")
        return name
