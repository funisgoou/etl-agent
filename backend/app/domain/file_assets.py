"""文件资产域（SPEC 3.5 / D8 / C3）：CSV 上传 MinIO + 表头解析与字段推断。"""

import csv
import io
import re

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.security as security
from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import ApiError
from app.core.minio_client import minio_client
from app.db_model import FileAsset

router = APIRouter(prefix="/api/v1", tags=["file-assets"])


def _infer_type(values: list[str]) -> str:
    """抽样类型推断：整数/浮点/空 → 其他 string。"""
    ints = floats = 0
    for v in values:
        if not v:
            continue
        try:
            int(v)
            ints += 1
        except ValueError:
            try:
                float(v)
                floats += 1
            except ValueError:
                return "string"
    nonempty = sum(1 for v in values if v)
    if nonempty and ints == nonempty:
        return "integer"
    if nonempty and ints + floats == nonempty:
        return "float"
    return "string"


@router.post("/file-assets", status_code=201)
async def upload_csv(
    project_id: int = ...,
    file: UploadFile | None = None,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """上传并解析 CSV：存 MinIO，推断 schema 落 file_assets.schema_json。"""
    # 1. 权限与格式护栏
    from app.domain.connections import _require_engineer

    await _require_engineer(project_id, user, db)
    if file is None or not (file.filename or "").lower().endswith(".csv"):
        raise ApiError("E_VALID_FILE_FORMAT", "v1 仅支持 CSV 文件（D8）")
    raw = await file.read()
    if len(raw) > 64 * 1024 * 1024:
        raise ApiError("E_VALID_FILE_FORMAT", "文件超过 64MB 上限")
    # 2. 先落库拿 id（对象键需要 file_asset_id）
    asset = FileAsset(project_id=project_id, file_name=file.filename or "upload.csv",
                      file_path="pending", file_size=len(raw), file_format="csv")
    db.add(asset)
    await db.flush()
    # 3. 对象键：projects/{pid}/file_assets/{id}/{name}（键名净化）
    safe_name = re.sub(r"[^\w.\-]", "_", asset.file_name)
    object_key = f"projects/{project_id}/file_assets/{asset.id}/{safe_name}"
    minio_client().put_object(
        get_settings().minio_bucket, object_key, io.BytesIO(raw), length=len(raw),
        content_type="text/csv",
    )
    asset.file_path = f"s3a://{get_settings().minio_bucket}/{object_key}"
    # 4. 表头解析 + 抽样类型推断（前 2000 行）
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise ApiError("E_VALID_FILE_FORMAT", "CSV 为空")
    header = rows[0]
    body_rows = rows[1:2001]
    columns = []
    for i, name in enumerate(header):
        vals = [r[i] if i < len(r) else "" for r in body_rows]
        columns.append({"name": name, "inferred_type": _infer_type(vals)})
    asset.schema_json = {"columns": columns, "row_count_sampled": len(body_rows)}
    await db.commit()
    return {
        "id": asset.id,
        "file_name": asset.file_name,
        "file_path": asset.file_path,
        "file_size": asset.file_size,
        "file_format": asset.file_format,
        "schema_json": asset.schema_json,
    }


@router.get("/projects/{project_id}/file-assets")
async def list_assets(
    project_id: int,
    page: int = 1,
    page_size: int = 20,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """项目文件资产列表（Page 信封）。"""
    from sqlalchemy import func

    await security.require_member(project_id)(user, db)
    q = select(FileAsset).where(FileAsset.project_id == project_id)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (
        await db.execute(q.order_by(FileAsset.id.desc()).offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    return {
        "items": [
            {
                "id": a.id, "file_name": a.file_name, "file_path": a.file_path,
                "file_size": a.file_size, "file_format": a.file_format, "schema_json": a.schema_json,
                "created_at": a.created_at,
            }
            for a in rows
        ],
        "total": total, "page": page, "page_size": page_size,
    }


@router.delete("/file-assets/{asset_id}", status_code=204)
async def remove_asset(
    asset_id: int,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> None:
    """删除文件资产：MinIO 对象 + DB 行（engineer 权限）。"""
    from app.core.errors import ApiError
    from app.domain.connections import _require_engineer

    asset = (await db.execute(select(FileAsset).where(FileAsset.id == asset_id))).scalar_one_or_none()
    if asset is None:
        raise ApiError("E_NOT_FOUND", f"文件资产不存在: {asset_id}")
    await _require_engineer(asset.project_id, user, db)
    # 1. MinIO 对象删除（s3a://bucket/key → bucket/key）
    path = asset.file_path.replace("s3a://", "")
    bucket, _, key = path.partition("/")
    try:
        minio_client().remove_object(bucket, key)
    except Exception:  # noqa: BLE001
        pass  # 对象可能已不存在；DB 行仍删除
    # 2. DB 删除
    await db.delete(asset)
    await db.commit()
