"""ORM 模型：控制面 23 张表（DATA 文档第 3 章）。

约定：表名小写蛇形复数；主键 BIGINT IDENTITY；时间 TIMESTAMPTZ 默认 now()；
JSON 字段 JSONB；枚举用 VARCHAR + CHECK；外键 ON DELETE RESTRICT。
audit_events / capability_tokens / outbox_events 等不建物理外键（安全内核解耦）。
"""

from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey,
                        Identity, Index, Integer, LargeBinary, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# ─────────────────────── 组织与权限 ───────────────────────


class User(Base):
    """用户：密码仅存散列。"""

    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    """项目（多项目隔离，无 tenant 字段）。"""

    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectMembership(Base):
    """项目成员（角色资格之一）。"""

    __tablename__ = "project_memberships"
    __table_args__ = (
        CheckConstraint("role in ('engineer','approver_data','approver_security','operator','auditor')"),
        UniqueConstraint("project_id", "user_id", "role"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectRoleGrant(Base):
    """职责槽资格表（D3：仅资格，互斥判定在 Prepare/Approve 服务端）。"""

    __tablename__ = "project_role_grants"
    __table_args__ = (
        CheckConstraint("role_slot in ('maker','checker1','checker2','operator')"),
        UniqueConstraint("project_id", "user_id", "role_slot"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role_slot: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    """会话：仅存 token_digest。"""

    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────── 连接与资产 ───────────────────────


class Connection(Base):
    """数据源连接：config_json 敏感字段仅存 vault:// 引用。"""

    __tablename__ = "connections"
    __table_args__ = (
        CheckConstraint(
            "conn_type in ('mysql','postgresql','oracle','doris','clickhouse','s3','rest_api')"
        ),
        UniqueConstraint("project_id", "name"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(128))
    conn_type: Mapped[str] = mapped_column(String(32), index=True)
    config_json: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MetadataProfile(Base):
    """只读元数据探查结果（只追加）。"""

    __tablename__ = "metadata_profiles"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("connections.id"), index=True)
    object_name: Mapped[str] = mapped_column(String(255), index=True)
    schema_json: Mapped[dict] = mapped_column(JSONB)
    stats_json: Mapped[dict | None] = mapped_column(JSONB)
    masked_sample_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FileAsset(Base):
    """CSV 文件资产（MinIO S3A，C3/D8）。"""

    __tablename__ = "file_assets"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(512), unique=True)
    file_size: Mapped[int] = mapped_column(BigInteger)
    file_format: Mapped[str] = mapped_column(String(16), default="csv")
    schema_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────── Pipeline 与制品 ───────────────────────


class Pipeline(Base):
    """Pipeline 定义。"""

    __tablename__ = "pipelines"
    __table_args__ = (UniqueConstraint("project_id", "code"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PipelineVersion(Base):
    """Pipeline 版本：冻结后 is_immutable=true，触发器拒绝 UPDATE/DELETE。"""

    __tablename__ = "pipeline_versions"
    __table_args__ = (UniqueConstraint("pipeline_id", "version_number"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipelines.id"))
    version_number: Mapped[int] = mapped_column(Integer)
    etl_plan_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    hocon_text: Mapped[str] = mapped_column(Text, default="")
    artifact_digest: Mapped[str] = mapped_column(String(64), unique=True)
    is_immutable: Mapped[bool] = mapped_column(Boolean, default=False)
    gate_report_json: Mapped[dict | None] = mapped_column(JSONB)  # 门禁报告（最近一次）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PipelineArtifact(Base):
    """版本制品（只追加）：编译产物 SQL 落 quality_contract_sql 类型。"""

    __tablename__ = "pipeline_artifacts"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("pipeline_versions.id"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(32))
    artifact_digest: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentRun(Base):
    """生成状态机业务投影（D10：不参与恢复，恢复走 checkpoint）。"""

    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("pipeline_versions.id"))
    thread_id: Mapped[str] = mapped_column(String(64), unique=True)
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="running")
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    pending_question_json: Mapped[dict | None] = mapped_column(JSONB)  # waiting_input 时的问题投影
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────── 审批与执行 ───────────────────────


class Preparation(Base):
    """准备单：冻结事实（除 status 外字段触发器冻结）。"""

    __tablename__ = "preparations"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("pipeline_versions.id"), index=True)
    maker_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    resource_scope: Mapped[dict] = mapped_column(JSONB)
    impact_json: Mapped[dict] = mapped_column(JSONB)
    data_classification: Mapped[str] = mapped_column(String(16))
    budget_json: Mapped[dict] = mapped_column(JSONB)
    rollback_plan_json: Mapped[dict] = mapped_column(JSONB)
    risk_level: Mapped[str] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApprovalRequest(Base):
    """审批单：同一准备单同一职责槽一张。"""

    __tablename__ = "approval_requests"
    __table_args__ = (UniqueConstraint("preparation_id", "required_role"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    preparation_id: Mapped[int] = mapped_column(ForeignKey("preparations.id"))
    version_id: Mapped[int] = mapped_column(ForeignKey("pipeline_versions.id"))
    required_role: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    decision: Mapped[str | None] = mapped_column(String(16))
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CapabilityToken(Base):
    """Capability 存证（D2：nonce 存证表 + 单事务消费，明文令牌不落库）。"""

    __tablename__ = "capability_tokens"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    subject_id: Mapped[int] = mapped_column(BigInteger)
    tool_intent: Mapped[str] = mapped_column(String(64))
    artifact_digest: Mapped[str] = mapped_column(String(64))
    nonce: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExecutionRun(Base):
    """执行运行实例：三阶段子状态 COPYING/SPLITTING/SWAPPING。"""

    __tablename__ = "execution_runs"
    __table_args__ = (
        CheckConstraint(
            "(run_kind = 'execute' AND preparation_id IS NOT NULL) OR "
            "(run_kind = 'dry_run' AND preparation_id IS NULL)"
        ),
        Index("ix_execution_runs_version_status", "version_id", "status"),
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("pipeline_versions.id"), index=True)
    preparation_id: Mapped[int | None] = mapped_column(ForeignKey("preparations.id"), index=True)
    run_kind: Mapped[str] = mapped_column(String(16), default="execute")
    capability_token_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    sub_stage: Mapped[str | None] = mapped_column(String(16))
    engine_job_id: Mapped[str | None] = mapped_column(String(128))
    input_records: Mapped[int | None] = mapped_column(BigInteger)
    output_records: Mapped[int | None] = mapped_column(BigInteger)
    error_records: Mapped[int | None] = mapped_column(BigInteger)
    bytes_processed: Mapped[int | None] = mapped_column(BigInteger)
    source_row_count: Mapped[int | None] = mapped_column(BigInteger)  # C1 判据①的源端行数基准
    row_count_check: Mapped[str | None] = mapped_column(String(16))  # passed/failed/pending
    diagnosis_json: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxEvent(Base):
    """事务性 Outbox：与业务事实同事务落库，中继投递 Celery。"""

    __tablename__ = "outbox_events"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(32))
    aggregate_id: Mapped[int] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RuntimeSupervisionSnapshot(Base):
    """运行时监督快照（只追加）。"""

    __tablename__ = "runtime_supervision_snapshots"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    execution_run_id: Mapped[int] = mapped_column(ForeignKey("execution_runs.id"), index=True)
    metrics_json: Mapped[dict] = mapped_column(JSONB)
    decision: Mapped[str] = mapped_column(String(16))
    action_taken: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────── 审计与评测 ───────────────────────


class AuditEvent(Base):
    """证据账本：哈希链只追加（触发器强制）。"""

    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(BigInteger, index=True)
    actor_id: Mapped[int] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str] = mapped_column(String(32))
    resource_id: Mapped[int] = mapped_column(BigInteger)
    payload_digest: Mapped[str] = mapped_column(String(64))
    prev_event_hash: Mapped[str] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), unique=True)
    payload_json: Mapped[dict | None] = mapped_column(JSONB)  # 载荷本体（账本校验含此字段）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BenchmarkCase(Base):
    """评测用例（版本化）。"""

    __tablename__ = "benchmark_cases"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    nl_requirement: Mapped[str] = mapped_column(Text)
    expected_schema_json: Mapped[dict] = mapped_column(JSONB)
    expected_risk_level: Mapped[str] = mapped_column(String(4))
    is_malicious: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BenchmarkRun(Base):
    """评测运行。"""

    __tablename__ = "benchmark_runs"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    suite_version: Mapped[str] = mapped_column(String(32))
    metrics_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvolutionCandidate(Base):
    """安全进化候选（prompt/policy）。"""

    __tablename__ = "evolution_candidates"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(255))
    content_json: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    review_report_json: Mapped[dict | None] = mapped_column(JSONB)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GrayFlag(Base):
    """灰度开关：enabled=true 前置 health_score>90（E_EVOLUTION_GATE）。"""

    __tablename__ = "gray_flags"
    __table_args__ = (UniqueConstraint("project_id", "flag_key"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    flag_key: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Keyring：Ed25519 密钥对存证（当前活跃密钥；轮转时追加新行）
class Keyring(Base):
    """Capability 签名密钥存证（私钥加密存 PG，仅签发进程解密）。"""

    __tablename__ = "keyring"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    key_id: Mapped[str] = mapped_column(String(64), unique=True)
    public_key_b64: Mapped[str] = mapped_column(String(128))
    encrypted_private_key: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
