"""连接与探查域（SPEC 3.3/3.4）：连接 CRUD、连通性测试、只读元数据探查。"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.security as security
from app.core.db import get_session
from app.core.errors import ApiError
from app.core.masking import mask_cell
from app.core.secret_provider import mask_config, redact_config, resolve_config
from app.db_model import Connection, MetadataProfile
from app.domain.connectors.base import CONNECTOR_REGISTRY, REGISTERED_TYPES

router = APIRouter(prefix="/api/v1", tags=["connections"])


class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    conn_type: str
    config_json: dict


def _conn_out(c: Connection) -> dict:
    return {
        "id": c.id,
        "project_id": c.project_id,
        "name": c.name,
        "conn_type": c.conn_type,
        "config_json": mask_config(c.config_json),
        "status": c.status,
        "created_at": c.created_at,
    }


async def _get_conn(db: AsyncSession, conn_id: int) -> Connection:
    c = (
        await db.execute(select(Connection).where(Connection.id == conn_id))
    ).scalar_one_or_none()
    if c is None:
        raise ApiError("E_NOT_FOUND", f"连接不存在: {conn_id}")
    return c


@router.get("/projects/{project_id}/connections")
async def list_connections(
    project_id: int,
    conn_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """项目连接列表（敏感字段掩码）。"""
    await security.require_member(project_id)(user, db)
    q = select(Connection).where(Connection.project_id == project_id)
    if conn_type:
        q = q.where(Connection.conn_type == conn_type)
    rows = (await db.execute(q.order_by(Connection.id.desc()).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    return {"items": [_conn_out(c) for c in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/projects/{project_id}/connections", status_code=201)
async def create_connection(
    project_id: int,
    body: ConnectionIn,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """创建连接：敏感字段经 redact_config 密文化后入库。"""
    # 1. 权限：engineer
    await _require_engineer(project_id, user, db)
    # 2. 类型注册表校验
    if body.conn_type not in REGISTERED_TYPES:
        raise ApiError("E_VALID_CONN_TYPE", f"不支持的连接类型: {body.conn_type}")
    # 3. 名称唯一
    dup = (
        await db.execute(
            select(Connection.id).where(Connection.project_id == project_id, Connection.name == body.name)
        )
    ).scalar_one_or_none()
    if dup:
        raise ApiError("E_VALID_REQUEST", f"连接名已存在: {body.name}")
    # 4. 入库（密文化）
    c = Connection(
        project_id=project_id,
        name=body.name,
        conn_type=body.conn_type,
        config_json=redact_config(body.config_json),
    )
    db.add(c)
    await db.commit()
    return _conn_out(c)


async def _require_engineer(project_id: int, user, db) -> None:
    """engineer/admin 角色校验。"""
    from app.db_model import ProjectMembership

    role = (
        await db.execute(
            select(ProjectMembership.role).where(
                ProjectMembership.project_id == project_id, ProjectMembership.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if role is None:
        raise ApiError("E_FORBIDDEN_PROJECT", "非项目成员")
    if role not in ("engineer", "admin"):
        raise ApiError("E_FORBIDDEN_PROJECT", "需要 engineer 角色")


@router.put("/connections/{conn_id}")
async def update_connection(
    conn_id: int,
    body: ConnectionIn,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """编辑连接：同样走密文化。"""
    c = await _get_conn(db, conn_id)
    await _require_engineer(c.project_id, user, db)
    c.name = body.name
    c.config_json = redact_config(body.config_json)
    await db.commit()
    return _conn_out(c)


@router.post("/connections/{conn_id}/tests")
async def test_connection(
    conn_id: int, user=Depends(security.current_user), db: AsyncSession = Depends(get_session)
) -> dict:
    """连通性测试：物化凭据 → 连接器 test()。"""
    c = await _get_conn(db, conn_id)
    await security.require_member(c.project_id)(user, db)
    connector = CONNECTOR_REGISTRY.get(c.conn_type)
    if connector is None:
        raise ApiError("E_VALID_CONN_TYPE", f"该类型暂不支持测试: {c.conn_type}")
    result = await connector.test(resolve_config(c.config_json))
    if not result.ok:
        c.status = "error"
    await db.commit()
    return {"ok": result.ok, "latency_ms": result.latency_ms, "server_version": result.server_version, "message": result.message}


@router.post("/connections/{conn_id}/profiles", status_code=201)
async def run_profile(
    conn_id: int,
    body: dict,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """只读元数据探查：结构 + 统计 + 脱敏样本（入库前全列扫描脱敏）。"""
    # 1. 权限与连接器
    c = await _get_conn(db, conn_id)
    await _require_engineer(c.project_id, user, db)
    connector = CONNECTOR_REGISTRY.get(c.conn_type)
    if connector is None:
        raise ApiError("E_VALID_CONN_TYPE", f"该类型暂不支持探查: {c.conn_type}")
    object_name = body.get("object_name", "")
    sample_size = min(int(body.get("sample_size", 100)), 1000)
    # 2. 探查（只读）
    result = await connector.profile(resolve_config(c.config_json), object_name, sample_size)
    # 3. 样本脱敏（不变式：masked_sample_json 不得含未脱敏敏感值）
    masked_sample = [
        {col: mask_cell(col, val) for col, val in row.items()} for row in result.sample
    ]
    # 4. 落库（只追加表）
    row = MetadataProfile(
        connection_id=c.id,
        object_name=object_name,
        schema_json=result.schema,
        stats_json=result.stats,
        masked_sample_json=masked_sample,
    )
    db.add(row)
    await db.commit()
    return {
        "id": row.id,
        "connection_id": c.id,
        "object_name": object_name,
        "schema_json": row.schema_json,
        "stats_json": row.stats_json,
        "masked_sample_json": row.masked_sample_json,
        "created_at": row.created_at,
    }


@router.get("/connections/{conn_id}/profiles")
async def list_profiles(
    conn_id: int,
    page: int = 1,
    page_size: int = 20,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """探查结果列表。"""
    c = await _get_conn(db, conn_id)
    await security.require_member(c.project_id)(user, db)
    rows = (
        await db.execute(
            select(MetadataProfile)
            .where(MetadataProfile.connection_id == conn_id)
            .order_by(MetadataProfile.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "connection_id": r.connection_id,
                "object_name": r.object_name,
                "schema_json": r.schema_json,
                "stats_json": r.stats_json,
                "masked_sample_json": r.masked_sample_json,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "total": len(rows),
        "page": page,
        "page_size": page_size,
    }
