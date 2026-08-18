/**
 * API DTO 类型定义 —— 与 docs/API-接口文档.md 严格对齐。
 * 页面开发只允许从这里导入类型，不要自行重复定义。
 */

/* ---------- 通用信封 ---------- */

/** 分页信封（API 1.3） */
export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

/** 健康检查（API 2） */
export interface HealthResp {
  status: 'ok' | 'degraded'
  components: Record<string, string>
}

/* ---------- 认证与用户 ---------- */

export type GlobalRole =
  | 'admin'
  | 'engineer'
  | 'approver_data'
  | 'approver_security'
  | 'operator'
  | 'auditor'

/** 职责槽（D3） */
export type RoleSlot = 'maker' | 'checker1' | 'checker2' | 'operator'

export interface User {
  id: number
  username: string
  display_name: string
  email: string
  status: 'active' | 'disabled'
  /** 平台角色全集（演示账号拥有全部） */
  roles?: GlobalRole[]
  /** 职责槽资格全集 */
  role_slots?: RoleSlot[]
}

export interface LoginResp {
  token: string
  expires_at: string
  user: User
}

/* ---------- 项目与成员 ---------- */

export interface Project {
  id: number
  name: string
  code: string
  description?: string
  created_at?: string
  /** 当前用户在该项目内的角色（详情接口返回） */
  my_role?: GlobalRole
}

export interface Member {
  user_id: number
  username: string
  display_name: string
  role: GlobalRole
  joined_at?: string
}

export interface RoleGrant {
  id: number
  project_id: number
  user_id: number
  display_name?: string
  role_slot: RoleSlot
  granted_at?: string
}

/* ---------- 数据连接与资产 ---------- */

export type ConnType =
  | 'mysql'
  | 'postgresql'
  | 'oracle'
  | 'doris'
  | 'clickhouse'
  | 's3'
  | 'rest_api'

export type ConnStatus = 'connected' | 'unreachable' | 'unknown'

export interface Connection {
  id: number
  project_id: number
  name: string
  conn_type: ConnType
  status: ConnStatus
  /** 敏感字段已掩码（pa***rd），永不返回明文 */
  config_json: Record<string, unknown>
  created_at: string
  updated_at?: string
}

export interface ProfileColumn {
  name: string
  type: string
  nullable?: boolean
  is_primary_key?: boolean
  /** 增量同步字段标记 */
  is_incremental?: boolean
  /** 敏感字段（脱敏对象） */
  sensitive?: boolean
  comment?: string
}

export interface Profile {
  id: number
  connection_id: number
  object_name: string
  schema_json: {
    columns: ProfileColumn[]
    primary_key: string[]
  }
  stats_json: { approx_rows: number; [k: string]: unknown }
  masked_sample_json: Record<string, unknown>[]
  created_at: string
}

export interface FileAssetColumn {
  name: string
  inferred_type: string
  sensitive?: boolean
  sample_masked?: string
}

export interface FileAsset {
  id: number
  project_id: number
  file_name: string
  file_path: string
  file_size: number
  file_format: 'csv'
  schema_json: { columns: FileAssetColumn[] }
  created_at: string
}

/* ---------- Pipeline 与生成 ---------- */

/** 版本状态机（D17）：draft→generating→gated→frozen→executing→executed/retired */
export type VersionStatus =
  | 'draft'
  | 'generating'
  | 'gated'
  | 'frozen'
  | 'executing'
  | 'executed'
  | 'retired'

export interface Pipeline {
  id: number
  project_id: number
  name: string
  code: string
  description?: string
  status: string
  latest_version_id?: number
  created_at: string
  updated_at?: string
}

export interface PipelineVersion {
  id: number
  pipeline_id: number
  version_number: number
  label?: string
  status: VersionStatus
  artifact_digest?: string | null
  base_version_id?: number | null
  created_at: string
}

export type AgentRunStatus = 'running' | 'waiting_input' | 'succeeded' | 'failed'

export interface AgentRunStep {
  name: string
  status: 'done' | 'running' | 'pending'
  detail?: string
}

/**
 * interrupt 表单字段 —— 由后端 schema 驱动渲染（SPEC 8 Studio）。
 * ASSUMED: 接口文档仅给出 {field,message} 简例，fields 数组为前端约定扩展。
 */
export interface PendingQuestionField {
  key: string
  label: string
  type: 'text' | 'select' | 'textarea'
  options?: string[]
  placeholder?: string
  required?: boolean
  value?: string
}

export interface PendingQuestion {
  message: string
  fields: PendingQuestionField[]
}

export interface AgentRun {
  run_id: number
  thread_id?: string
  version_id?: number
  status: AgentRunStatus
  step_count?: number
  /** 步骤时间线（演示约定扩展字段） */
  steps?: AgentRunStep[]
  pending_question?: PendingQuestion | null
}

/* ---------- 设计结果（EtlPlan / HOCON / DAG / 门禁） ---------- */

export interface FieldMapping {
  source_field: string
  source_type?: string
  target_field: string
  target_type?: string
  renamed?: boolean
  transform?: string
  comment?: string
}

export interface MaskingRule {
  field: string
  rule: string
  description?: string
  sample_before?: string
  sample_after?: string
  enforced: boolean
}

export interface QualityRule {
  code: string
  field?: string
  expression: string
  description?: string
  severity?: 'blocking' | 'warning'
}

export interface EtlPlan {
  source: { kind: string; connection?: string; table?: string; file_asset_id?: number }
  target: { kind: string; connection?: string; table: string }
  sync_mode?: string
  incremental_field?: string
  schedule?: string
  engine?: string
  publish_strategy?: string
  estimated_full_rows?: number
  estimated_daily_rows?: number
  mappings: FieldMapping[]
  masking_rules: MaskingRule[]
  quality_contract: { rules: QualityRule[] }
  [k: string]: unknown
}

export interface DagNode {
  id: string
  label: string
  kind: string
  sub?: string
  detail?: string
}

export interface DagEdge {
  from: string
  to: string
}

export interface GateFinding {
  code: string
  name: string
  status: 'passed' | 'failed' | 'warning'
  blocking?: boolean
  message?: string
}

export interface GateReport {
  passed: boolean
  total?: number
  passed_count?: number
  findings: GateFinding[]
}

export interface DesignResult {
  version_id: number
  status: string
  etl_plan?: EtlPlan
  hocon?: string
  dag?: { nodes: DagNode[]; edges: DagEdge[] }
  gate_report?: GateReport
  artifact_digest?: string | null
  is_immutable: boolean
}

/* ---------- 三阶段协议 ---------- */

export type RiskLevel = 'P0' | 'P1' | 'P2' | 'P3'

export type PrepStatus =
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'committed'
  | 'expired'
  | 'cancelled'

export interface ApprovalRequest {
  id: number
  preparation_id?: number
  required_role: RoleSlot
  status: 'pending' | 'decided'
  decision?: 'approve' | 'reject' | null
  approver_id?: number | null
  approver_name?: string
  comment?: string
  decided_at?: string | null
}

export interface Preparation {
  id: number
  version_id: number
  pipeline_id?: number
  pipeline_name?: string
  status: PrepStatus
  maker_id: number
  maker_name?: string
  expires_at: string
  input_fingerprint: string
  resource_scope: Record<string, string[]>
  impact_json: Record<string, unknown>
  data_classification: string
  budget_json: {
    max_credits?: number
    max_duration_seconds?: number
    max_read_rows?: number
    max_write_bytes?: number
  }
  rollback_plan_json: { steps: string[] }
  risk_level: RiskLevel
  approval_requests: ApprovalRequest[]
  created_at?: string
  audit_event_id?: number
}

/* ---------- 执行运行 ---------- */

export type RunStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'rolled_back'

export type RunKind = 'execute' | 'dry_run'
export type SubStage = 'COPYING' | 'SPLITTING' | 'SWAPPING'

export interface QualityReport {
  row_count_check: 'pending' | 'passed' | 'failed'
  error_code_distribution: Record<string, number>
  contract_hits: Record<string, number>
}

export interface Diagnosis {
  root_cause: string
  suggestions: string[]
}

export interface ExecutionRun {
  id: number
  version_id: number
  pipeline_id?: number
  pipeline_name?: string
  preparation_id?: number | null
  run_kind: RunKind
  status: RunStatus
  sub_stage?: SubStage | null
  engine_job_id?: string
  input_records: number
  output_records: number
  error_records: number
  bytes_processed: number
  started_at?: string | null
  finished_at?: string | null
  diagnosis?: Diagnosis | null
  quality_report?: QualityReport | null
  created_at?: string
}

/* ---------- Benchmark ---------- */

export interface BenchmarkMetrics {
  compile_pass_rate: number
  field_f1: number
  dry_run_pass_rate: number
  block_rate: number
  false_positive_rate: number
  health_score: number
}

export interface BenchmarkRun {
  id: number
  suite_version: string
  status: RunStatus
  metrics_json?: BenchmarkMetrics | null
  started_at?: string
  finished_at?: string
}

/* ---------- 审计 ---------- */

export interface AuditEvent {
  id: number
  project_id: number
  event_type: string
  actor_id?: number
  actor_name?: string
  resource_type?: string
  resource_id?: string
  summary: string
  payload_json?: Record<string, unknown>
  prev_event_hash: string
  event_hash: string
  created_at: string
}

export interface VerifyResult {
  project_id: number
  ok: boolean
  checked_events: number
  broken_at_event_id: number | null
  expected_hash?: string | null
  actual_hash?: string | null
}

/* ---------- 安全进化 ---------- */

export interface EvolutionCandidate {
  id: number
  project_id: number
  kind: 'prompt' | 'policy'
  title: string
  content_json: Record<string, unknown>
  status: 'proposed' | 'approved' | 'rejected'
  review_report_json?: Record<string, unknown>
  /** 评审对比：变更前 → 变更后健康度（演示字段） */
  health_before?: number
  health_after?: number
  created_by: number
  created_by_name?: string
  created_at: string
  updated_at: string
}

export interface GrayFlag {
  project_id: number
  flag_key: string
  enabled: boolean
  description: string
  /** 影响范围说明（演示字段） */
  impact_scope?: string
  updated_by?: number
  updated_at: string
}
