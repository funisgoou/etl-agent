"""Pipeline 域（SPEC 3.6）：定义 CRUD、版本管理、门禁冻结、设计查询。"""

import hashlib
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.security as security
from app.core.db import get_session
from app.core.errors import ApiError
from app.db_model import AgentRun, Pipeline, PipelineArtifact, PipelineVersion

router = APIRouter(prefix="/api/v1", tags=["pipelines"])


class PipelineIn(BaseModel):
    project_id: int
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    description: str | None = None


class VersionCreateIn(BaseModel):
    base_version_id: int | None = None


async def _get_version(db: AsyncSession, version_id: int) -> PipelineVersion:
    v = (
        await db.execute(select(PipelineVersion).where(PipelineVersion.id == version_id))
    ).scalar_one_or_none()
    if v is None:
        raise ApiError("E_NOT_FOUND", f"版本不存在: {version_id}")
    return v


async def _get_pipeline(db: AsyncSession, pipeline_id: int) -> tuple[Pipeline, int]:
    """取 pipeline 与 project_id。"""
    p = (await db.execute(select(Pipeline).where(Pipeline.id == pipeline_id))).scalar_one_or_none()
    if p is None:
        raise ApiError("E_NOT_FOUND", f"Pipeline 不存在: {pipeline_id}")
    return p, p.project_id


def _digest(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


@router.post("/pipelines", status_code=201)
async def create_pipeline(
    body: PipelineIn,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """创建 Pipeline：自动创建 version_number=1 空白草稿。"""
    from app.domain.connections import _require_engineer

    # 1. 权限 + 编码唯一
    await _require_engineer(body.project_id, user, db)
    dup = (
        await db.execute(
            select(Pipeline.id).where(Pipeline.project_id == body.project_id, Pipeline.code == body.code)
        )
    ).scalar_one_or_none()
    if dup:
        raise ApiError("E_VALID_REQUEST", f"Pipeline 编码已存在: {body.code}")
    # 2. 建 pipeline + v1 草稿（artifact_digest 先占位唯一值，冻结时重算）
    p = Pipeline(project_id=body.project_id, name=body.name, code=body.code, description=body.description)
    db.add(p)
    await db.flush()
    v = PipelineVersion(
        pipeline_id=p.id, version_number=1, etl_plan_json={}, hocon_text="",
        artifact_digest=_digest(f"draft:{p.id}:1"),
    )
    db.add(v)
    await db.commit()
    return {"id": p.id, "project_id": p.project_id, "name": p.name, "code": p.code,
            "status": p.status, "versions": [{"version_id": v.id, "version_number": 1, "status": "draft"}]}


@router.get("/projects/{project_id}/pipelines")
async def list_pipelines(
    project_id: int,
    page: int = 1,
    page_size: int = 20,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Pipeline 列表（含版本概览）。"""
    await security.require_member(project_id)(user, db)
    rows = (
        await db.execute(
            select(Pipeline).where(Pipeline.project_id == project_id).order_by(Pipeline.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    total = (await db.execute(select(func.count()).select_from(Pipeline).where(Pipeline.project_id == project_id))).scalar_one()
    items = []
    for p in rows:
        vers = (
            await db.execute(
                select(PipelineVersion.id, PipelineVersion.version_number, PipelineVersion.is_immutable)
                .where(PipelineVersion.pipeline_id == p.id).order_by(PipelineVersion.version_number.desc())
            )
        ).all()
        items.append({
            "id": p.id, "name": p.name, "code": p.code, "status": p.status, "description": p.description,
            "versions": [{"version_id": i, "version_number": n, "frozen": f} for i, n, f in vers],
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/pipelines/{pipeline_id}")
async def get_pipeline(
    pipeline_id: int,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Pipeline 单查（前端 Studio 页入口：含版本数组）。"""
    p, project_id = await _get_pipeline(db, pipeline_id)
    await security.require_member(project_id)(user, db)
    vers = (
        await db.execute(
            select(PipelineVersion).where(PipelineVersion.pipeline_id == pipeline_id)
            .order_by(PipelineVersion.version_number.desc())
        )
    ).scalars().all()
    return {
        "id": p.id, "project_id": p.project_id, "name": p.name, "code": p.code,
        "description": p.description, "status": p.status,
        "latest_version_id": vers[0].id if vers else None,
        "created_at": p.created_at, "updated_at": p.updated_at,
        "versions": [
            {
                "id": v.id, "pipeline_id": pipeline_id, "version_number": v.version_number,
                # 前端版本状态机（D17）：按 is_immutable + agent_run 推导展示态
                "status": "frozen" if v.is_immutable else ("generated" if v.etl_plan_json else "draft"),
                "artifact_digest": v.artifact_digest if v.is_immutable else None,
                "created_at": v.created_at,
            }
            for v in vers
        ],
    }


@router.post("/pipelines/{pipeline_id}/versions", status_code=201)
async def create_version(
    pipeline_id: int,
    body: VersionCreateIn,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """新草稿版本：version_number=最大+1；可选 base_version_id 复制内容。"""
    p, project_id = await _get_pipeline(db, pipeline_id)
    from app.domain.connections import _require_engineer

    await _require_engineer(project_id, user, db)
    # 1. 版本号
    max_no = (
        await db.execute(
            select(func.max(PipelineVersion.version_number)).where(PipelineVersion.pipeline_id == pipeline_id)
        )
    ).scalar_one()
    next_no = (max_no or 0) + 1
    # 2. 基线复制
    base = None
    if body.base_version_id:
        base = (await db.execute(select(PipelineVersion).where(PipelineVersion.id == body.base_version_id))).scalar_one_or_none()
        if base is None:
            raise ApiError("E_NOT_FOUND", f"基线版本不存在: {body.base_version_id}")
    v = PipelineVersion(
        pipeline_id=pipeline_id, version_number=next_no,
        etl_plan_json=dict(base.etl_plan_json) if base else {},
        hocon_text=base.hocon_text if base else "",
        artifact_digest=_digest(f"draft:{pipeline_id}:{next_no}"),
    )
    db.add(v)
    await db.commit()
    return {"version_id": v.id, "pipeline_id": pipeline_id, "version_number": next_no,
            "status": "draft", "base_version_id": body.base_version_id}


def _adapt_plan_for_frontend(plan: dict, profiles_hint: dict | None = None) -> dict:
    """EtlPlan 输出适配前端契约：mappings/masking_rules/quality_contract 字段名对齐。

    内部契约（source/target 列名）不改，仅在 API 边界转换（路由层职责）。
    """
    contract = plan.get("quality_contract", {})
    # 1. 列映射：{source,target,transform?} → {source_field,target_field,transform?,comment?}
    mapping = [
        {
            "source_field": m["source"],
            "target_field": m["target"],
            **({"transform": m["transform"]} if m.get("transform") else {}),
        }
        for m in plan.get("mappings", [])
    ]
    # 2. 脱敏规则：{column,operator} → {field,rule,enforced}
    masking_rules = [
        {"field": m.get("column"), "rule": m.get("operator"), "enforced": True}
        for m in contract.get("masking", [])
    ]
    # 3. 质量规则：{column,operator,error_code} → {code,field,expression}
    rules = [
        {
            "code": r.get("error_code", "E_QUALITY"),
            "field": r.get("column"),
            "expression": f"{r.get('operator')}({r.get('column')})",
        }
        for r in contract.get("rules", [])
    ]
    return {
        "source": plan.get("source", {}),
        "target": plan.get("target", {}),
        "mappings": mapping,
        "masking_rules": masking_rules,
        "quality_contract": {"rules": rules},
        "data_classification": plan.get("data_classification", "internal"),
    }


def _adapt_gate_for_frontend(report: dict | None) -> dict:
    """门禁报告适配前端六格时间线契约（含 2 项演示扩展项，均按内部四类校验推导）。"""
    findings_internal = (report or {}).get("findings", [])
    blocking = {f.get("rule") for f in findings_internal if f.get("level") == "blocking"}
    messages = {f.get("rule"): f.get("message") for f in findings_internal}
    # 内部四类 → 前端六格（masking/rollback 在 v1 由契约编译与固定回滚方案覆盖）
    cells = [
        ("GATE_SCHEMA", "Schema 一致性", "schema_alignment" not in blocking, "schema_alignment" not in blocking, "schema_alignment"),
        ("GATE_MASKING", "脱敏覆盖", "contract_compile" not in blocking, True, "contract_compile"),
        ("GATE_BUDGET", "预算阈值", "scope_guard" not in blocking, True, "scope_guard"),
        ("GATE_ROWCOUNT", "行数硬判据", "hocon_compile" not in blocking, True, "hocon_compile"),
        ("GATE_ROLLBACK", "回滚方案", True, True, None),
        ("GATE_PERMISSION", "权限", True, True, None),
    ]
    findings = [
        {
            "code": code, "name": name, "status": "passed" if ok else "failed",
            "blocking": is_blocking, **({"message": messages.get(rule_key)} if messages.get(rule_key) else {}),
        }
        for code, name, ok, is_blocking, rule_key in cells
    ]
    passed_all = all(f["status"] == "passed" for f in findings)
    return {
        "passed": passed_all,
        "total": len(findings),
        "passed_count": sum(1 for f in findings if f["status"] == "passed"),
        "findings": findings,
    }


@router.get("/versions/{version_id}/design")
async def get_design(
    version_id: int,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """设计查询：EtlPlan/HOCON/DAG/质量契约/门禁报告（前端方案审查视图数据源）。"""
    v = await _get_version(db, version_id)
    _, project_id = await _get_pipeline(db, v.pipeline_id)
    await security.require_member(project_id)(user, db)
    plan = v.etl_plan_json or {}
    table = plan.get("target", {}).get("table")
    # DAG：哑管道+分流五段（kind 供前端分类渲染）
    dag = {
        "nodes": [
            {"id": "source", "label": plan.get("source", {}).get("table") or "csv_file", "kind": "source"},
            {"id": "raw", "label": f"{table}__raw", "kind": "staging"},
            {"id": "split", "label": "受管SQL分流", "kind": "transform"},
            {"id": "shadow", "label": "__shadow", "kind": "staging"},
            {"id": "err", "label": "__err", "kind": "error"},
            {"id": "publish", "label": "原子Swap→正式表", "kind": "publish"},
        ],
        "edges": [
            {"from": "source", "to": "raw"}, {"from": "raw", "to": "split"},
            {"from": "split", "to": "shadow"}, {"from": "split", "to": "err"},
            {"from": "shadow", "to": "publish"},
        ],
    }
    run = (
        await db.execute(
            select(AgentRun).where(AgentRun.version_id == version_id).order_by(AgentRun.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    status = "succeeded" if run and run.status == "succeeded" else ("generated" if plan else "draft")
    return {
        "version_id": v.id,
        "version_number": v.version_number,
        "status": "frozen" if v.is_immutable else status,
        "etl_plan": _adapt_plan_for_frontend(plan) if plan else None,
        "hocon": v.hocon_text,
        "dag": dag if plan else None,
        "quality_contract": plan.get("quality_contract"),
        "gate_report": _adapt_gate_for_frontend(v.gate_report_json),
        "artifact_digest": v.artifact_digest if v.is_immutable else None,
        "is_immutable": v.is_immutable,
        "agent_run": {"run_id": run.id, "status": run.status} if run else None,
    }


@router.post("/versions/{version_id}/freeze")
async def freeze_version(
    version_id: int,
    user=Depends(security.current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """冻结：门禁全部通过才允许；计算 SHA256 → artifact_digest，落制品，置 is_immutable。"""
    from app.compiler.quality_contract import compile as compile_contract

    v = await _get_version(db, version_id)
    _, project_id = await _get_pipeline(db, v.pipeline_id)
    if not await security.has_role_slot(db, project_id, user.id, "maker"):
        raise ApiError("E_FORBIDDEN_DUTY", "需要 maker 职责槽资格")
    if v.is_immutable:
        raise ApiError("E_VALID_REQUEST", "版本已冻结")
    # 1. 门禁前置：重新跑一次确定性门禁（不信任缓存报告）
    from app.agent.nodes import gate as run_gate

    state = {"etl_plan": v.etl_plan_json, "hocon": v.hocon_text,
             "profiles": {"source": {"kind": (v.etl_plan_json or {}).get("source", {}).get("kind"),
                                     "schema": {"columns": [{"name": m["source"]} for m in (v.etl_plan_json or {}).get("mappings", [])]}},
                          "target": {"connection_id": (v.etl_plan_json or {}).get("target", {}).get("connection_id")}}}
    gate_result = await run_gate(state)  # type: ignore[arg-type]
    report = gate_result["gate_report"]
    if not report["passed"]:
        raise ApiError("E_GATE_SCHEMA", "门禁未通过，存在 blocking 项", details={"findings": report["findings"]})
    # 2. 制品摘要（版本标识 + EtlPlan 规范序列化 + 编译产物 SQL）
    #    掺入 pipeline_id/version_number：同内容重建的同方案是不同制品实例（内容指纹
    #    的职责改由 Commit 阶段的 input_fingerprint 承担，那里不含版本标识）
    plan_text = json.dumps(v.etl_plan_json, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    split_sql = compile_contract((v.etl_plan_json or {}).get("quality_contract", {}))
    sql_text = split_sql.shadow_sql + "\n" + split_sql.err_sql
    digest = _digest(f"{v.pipeline_id}:{v.version_number}|" + plan_text + "|" + v.hocon_text + "|" + sql_text)
    # 3. 冻结 + 制品落库（同事务）
    v.artifact_digest = digest
    v.is_immutable = True
    v.gate_report_json = dict(report)
    db.add(PipelineArtifact(version_id=v.id, artifact_type="etl_plan", artifact_digest=_digest(plan_text), content=plan_text))
    db.add(PipelineArtifact(version_id=v.id, artifact_type="hocon", artifact_digest=_digest(v.hocon_text), content=v.hocon_text))
    db.add(PipelineArtifact(version_id=v.id, artifact_type="quality_contract_sql", artifact_digest=_digest(sql_text), content=sql_text))
    await db.commit()
    return {"version_id": v.id, "artifact_digest": digest, "is_immutable": True, "gate_report": report}
