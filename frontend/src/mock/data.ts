/**
 * Mock 演示数据集 —— 与 design/ 原型一致，跨页引用自洽。
 * 仅数据，不含行为逻辑（动态时间线在 db.ts）。
 */
import type {
  AuditEvent,
  BenchmarkRun,
  Connection,
  DesignResult,
  EvolutionCandidate,
  ExecutionRun,
  FileAsset,
  GrayFlag,
  Member,
  Pipeline,
  PipelineVersion,
  Preparation,
  Profile,
  Project,
  RoleGrant,
  User,
} from '../api/types'

const DAY = 86_400_000

/** 相对当前时间 n 天前的 ISO 字符串（保证演示时趋势图总有近 7 天数据） */
export function daysAgo(n: number, hour = 10): string {
  const d = new Date(Date.now() - n * DAY)
  d.setHours(hour, Math.floor(Math.random() * 50) + 5, 0, 0)
  return d.toISOString()
}

export function isoIn(ms: number): string {
  return new Date(Date.now() + ms).toISOString()
}

/** 简化哈希（仅演示账本链，非密码学用途）：生成 16 位 hex */
export function demoHash(input: string): string {
  let h1 = 0x811c9dc5
  let h2 = 0x01000193
  for (let i = 0; i < input.length; i++) {
    const c = input.charCodeAt(i)
    h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0
    h2 = Math.imul(h2 ^ c, 0x85ebca6b) >>> 0
  }
  return h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0')
}

/* ---------- 用户 ---------- */

export const users: User[] = [
  {
    id: 2,
    username: 'zhangwei',
    display_name: '张伟',
    email: 'zhangwei@example.com',
    status: 'active',
    roles: ['admin', 'engineer', 'approver_data', 'approver_security', 'operator', 'auditor'],
    role_slots: ['maker', 'checker1', 'checker2', 'operator'],
  },
  {
    id: 3,
    username: 'lina',
    display_name: '李娜',
    email: 'lina@example.com',
    status: 'active',
    roles: ['approver_data'],
    role_slots: ['checker1'],
  },
  {
    id: 4,
    username: 'wangqiang',
    display_name: '王强',
    email: 'wangqiang@example.com',
    status: 'active',
    roles: ['approver_security'],
    role_slots: ['checker2'],
  },
  {
    id: 1,
    username: 'admin',
    display_name: '系统管理员',
    email: 'admin@example.com',
    status: 'active',
    roles: ['admin', 'operator'],
    role_slots: ['operator'],
  },
]

/** 当前登录用户（任意账号密码登录成功，固定返回张伟全角色） */
export const currentUser = users[0]

/* ---------- 项目 / 成员 / 资格 ---------- */

export const projects: Project[] = [
  { id: 1, name: '电商数据中台', code: 'dmp', description: '订单 / 用户 / 退款核心域入仓', created_at: daysAgo(30), my_role: 'admin' },
  { id: 2, name: '用户增长分析', code: 'ugrowth', description: '增长实验与留存分析数据链路', created_at: daysAgo(22), my_role: 'engineer' },
  { id: 3, name: '财务数据仓库', code: 'fin_dw', description: '对账与财务报表归档', created_at: daysAgo(15), my_role: 'engineer' },
]

export const members: (Member & { project_id: number })[] = [
  { project_id: 1, user_id: 2, username: 'zhangwei', display_name: '张伟', role: 'admin', joined_at: daysAgo(30) },
  { project_id: 1, user_id: 3, username: 'lina', display_name: '李娜', role: 'approver_data', joined_at: daysAgo(28) },
  { project_id: 1, user_id: 4, username: 'wangqiang', display_name: '王强', role: 'approver_security', joined_at: daysAgo(28) },
  { project_id: 1, user_id: 1, username: 'admin', display_name: '系统管理员', role: 'operator', joined_at: daysAgo(30) },
]

export const roleGrants: RoleGrant[] = [
  { id: 1, project_id: 1, user_id: 2, display_name: '张伟', role_slot: 'maker', granted_at: daysAgo(29) },
  { id: 2, project_id: 1, user_id: 3, display_name: '李娜', role_slot: 'checker1', granted_at: daysAgo(28) },
  { id: 3, project_id: 1, user_id: 4, display_name: '王强', role_slot: 'checker2', granted_at: daysAgo(28) },
  { id: 4, project_id: 1, user_id: 1, display_name: '系统管理员', role_slot: 'operator', granted_at: daysAgo(30) },
  { id: 5, project_id: 1, user_id: 2, display_name: '张伟', role_slot: 'checker1', granted_at: daysAgo(28) },
  { id: 6, project_id: 1, user_id: 2, display_name: '张伟', role_slot: 'checker2', granted_at: daysAgo(28) },
  { id: 7, project_id: 1, user_id: 2, display_name: '张伟', role_slot: 'operator', granted_at: daysAgo(28) },
]

/* ---------- 连接 / 探查 / 文件资产 ---------- */

export const connections: Connection[] = [
  {
    id: 1, project_id: 1, name: 'mysql_prod_orders', conn_type: 'mysql', status: 'connected',
    config_json: { host: '10.0.4.12', port: 3306, database: 'trade', username: 'etl', password: 'pa***rd' },
    created_at: daysAgo(26),
  },
  {
    id: 2, project_id: 1, name: 'pg_user_center', conn_type: 'postgresql', status: 'connected',
    config_json: { host: '10.0.4.21', port: 5432, database: 'user_center', username: 'etl', password: 'pa***rd' },
    created_at: daysAgo(25),
  },
  {
    id: 3, project_id: 1, name: 'oracle_finance', conn_type: 'oracle', status: 'unreachable',
    config_json: { host: '10.0.6.8', port: 1521, database: 'FINDB', username: 'etl_ro', password: 'pa***rd' },
    created_at: daysAgo(24),
  },
  {
    id: 4, project_id: 1, name: 'ch_log_warehouse', conn_type: 'clickhouse', status: 'connected',
    config_json: { host: '10.0.5.30', port: 8123, database: 'logs', username: 'etl', password: 'pa***rd' },
    created_at: daysAgo(20),
  },
  {
    id: 5, project_id: 1, name: 'doris_dw', conn_type: 'doris', status: 'connected',
    config_json: { host: 'doris-fe', port: 8030, database: 'dwd', username: 'etl', password: 'pa***rd' },
    created_at: daysAgo(19),
  },
  {
    id: 6, project_id: 1, name: 'mysql_crm', conn_type: 'mysql', status: 'connected',
    config_json: { host: '10.0.7.16', port: 3306, database: 'crm', username: 'etl', password: 'pa***rd' },
    created_at: daysAgo(12),
  },
]

export const profiles: Profile[] = [
  {
    id: 7,
    connection_id: 1,
    object_name: 'orders',
    schema_json: {
      primary_key: ['id'],
      columns: [
        { name: 'id', type: 'BIGINT', nullable: false, is_primary_key: true, comment: '主键' },
        { name: 'order_no', type: 'VARCHAR(32)', nullable: false, comment: '订单号' },
        { name: 'user_id', type: 'BIGINT', nullable: false, comment: '用户 ID' },
        { name: 'email', type: 'VARCHAR(64)', nullable: true, sensitive: true, comment: '邮箱（敏感）' },
        { name: 'phone', type: 'VARCHAR(20)', nullable: true, sensitive: true, comment: '手机号（敏感）' },
        { name: 'amount', type: 'DECIMAL(10,2)', nullable: false, comment: '订单金额' },
        { name: 'status', type: 'VARCHAR(16)', nullable: false, comment: '订单状态' },
        { name: 'created_at', type: 'DATETIME', nullable: false, is_incremental: true, comment: '创建时间（增量字段）' },
      ],
    },
    stats_json: { approx_rows: 1_204_332 },
    masked_sample_json: [
      { id: 100231, order_no: 'SO20260611001', user_id: 88021, email: 'x***@example.com', phone: '138****5678', amount: 329.0, status: 'paid', created_at: '2026-06-11 02:13:44' },
      { id: 100232, order_no: 'SO20260611002', user_id: 91307, email: 'l***@example.com', phone: '137****9021', amount: 88.5, status: 'paid', created_at: '2026-06-11 02:14:02' },
      { id: 100233, order_no: 'SO20260611003', user_id: 40218, email: 'w***@example.com', phone: '150****3316', amount: 1204.9, status: 'refunded', created_at: '2026-06-11 02:15:37' },
    ],
    created_at: daysAgo(6),
  },
]

export const fileAssets: FileAsset[] = [
  {
    id: 5, project_id: 1, file_name: 'orders_export.csv', file_size: 25_794_970, file_format: 'csv',
    file_path: 's3a://etl-assets/projects/1/file_assets/5/orders_export.csv',
    schema_json: {
      columns: [
        { name: 'id', inferred_type: 'long' },
        { name: 'order_no', inferred_type: 'string' },
        { name: 'email', inferred_type: 'string', sensitive: true, sample_masked: 'x***@example.com' },
        { name: 'amount', inferred_type: 'decimal' },
        { name: 'created_at', inferred_type: 'datetime' },
      ],
    },
    created_at: daysAgo(5),
  },
  {
    id: 6, project_id: 1, file_name: 'users_snapshot.csv', file_size: 8_493_466, file_format: 'csv',
    file_path: 's3a://etl-assets/projects/1/file_assets/6/users_snapshot.csv',
    schema_json: {
      columns: [
        { name: 'user_id', inferred_type: 'long' },
        { name: 'nickname', inferred_type: 'string' },
        { name: 'phone', inferred_type: 'string', sensitive: true, sample_masked: '138****5678' },
        { name: 'city', inferred_type: 'string' },
      ],
    },
    created_at: daysAgo(4),
  },
  {
    id: 7, project_id: 1, file_name: 'refund_q2.csv', file_size: 138_831_462, file_format: 'csv',
    file_path: 's3a://etl-assets/projects/1/file_assets/7/refund_q2.csv',
    schema_json: {
      columns: [
        { name: 'refund_id', inferred_type: 'long' },
        { name: 'order_no', inferred_type: 'string' },
        { name: 'refund_amount', inferred_type: 'decimal' },
        { name: 'reason', inferred_type: 'string' },
      ],
    },
    created_at: daysAgo(3),
  },
  {
    id: 8, project_id: 1, file_name: 'dim_region.csv', file_size: 419_430, file_format: 'csv',
    file_path: 's3a://etl-assets/projects/1/file_assets/8/dim_region.csv',
    schema_json: {
      columns: [
        { name: 'region_code', inferred_type: 'string' },
        { name: 'region_name', inferred_type: 'string' },
        { name: 'parent_code', inferred_type: 'string' },
      ],
    },
    created_at: daysAgo(2),
  },
]

/* ---------- Pipeline / 版本 / 设计 ---------- */

export const pipelines: Pipeline[] = [
  { id: 7, project_id: 1, name: 'orders 每日增量同步', code: 'orders_dwd', description: 'MySQL orders → Doris raw_orders，每日 02:00 增量', status: 'active', latest_version_id: 42, created_at: daysAgo(8) },
  { id: 8, project_id: 1, name: 'user_center 全量归档', code: 'user_center_archive', description: 'PG 用户中心每日全量快照归档', status: 'active', created_at: daysAgo(7) },
  { id: 9, project_id: 1, name: 'refund 明细清洗', code: 'refund_dwd', description: '退款 CSV 明细清洗入仓', status: 'active', created_at: daysAgo(6) },
  { id: 10, project_id: 1, name: 'dim_region 维表同步', code: 'dim_region_sync', description: '地域维表小时级同步', status: 'active', created_at: daysAgo(5) },
  { id: 11, project_id: 1, name: 'crm_contract 抽取', code: 'crm_contract_extract', description: 'CRM 合同表抽取至 ClickHouse', status: 'draft', created_at: daysAgo(3) },
]

export const versions: PipelineVersion[] = [
  {
    id: 42, pipeline_id: 7, version_number: 1, label: 'v1.0', status: 'frozen',
    artifact_digest: '9f2e4a8b3c5d7e19f0a2b4c6d8e0f1a3b5c7d9e1f2a4b6c8d0e2f4a6b8c0d2e4c21d',
    base_version_id: null, created_at: daysAgo(6),
  },
]

/** version 42 完整设计结果（生成完成后由 GET design 返回） */
export const design42: DesignResult = {
  version_id: 42,
  status: 'generated',
  is_immutable: true,
  artifact_digest: versions[0].artifact_digest,
  etl_plan: {
    source: { kind: 'mysql', connection: 'mysql_prod_orders', table: 'orders' },
    target: { kind: 'doris', connection: 'doris_dw', table: 'raw_orders' },
    sync_mode: '增量 · 每日 02:00',
    incremental_field: 'created_at',
    schedule: '0 2 * * *',
    engine: 'SeaTunnel Zeta',
    publish_strategy: 'shadow 原子发布（raw_orders_shadow → 校验通过 → Swap 正式表）',
    estimated_full_rows: 1_204_332,
    estimated_daily_rows: 3_400,
    mappings: [
      { source_field: 'id', source_type: 'BIGINT', target_field: 'id', target_type: 'BIGINT', comment: '主键' },
      { source_field: 'order_no', source_type: 'VARCHAR(32)', target_field: 'order_no', target_type: 'VARCHAR(32)' },
      { source_field: 'user_id', source_type: 'BIGINT', target_field: 'user_id', target_type: 'BIGINT' },
      { source_field: 'email', source_type: 'VARCHAR(64)', target_field: 'email', target_type: 'VARCHAR(64)', transform: 'mask_email', comment: '脱敏 · 邮箱掩码' },
      { source_field: 'phone', source_type: 'VARCHAR(20)', target_field: 'phone', target_type: 'VARCHAR(20)', transform: 'mask_phone', comment: '脱敏 · 手机号掩码' },
      { source_field: 'amount', source_type: 'DECIMAL(10,2)', target_field: 'amount', target_type: 'DECIMAL(10,2)' },
      { source_field: 'status', source_type: 'VARCHAR(16)', target_field: 'order_status', target_type: 'VARCHAR(16)', renamed: true, comment: '字段改名' },
      { source_field: 'created_at', source_type: 'DATETIME', target_field: 'dt', target_type: 'DATETIME', renamed: true, comment: '改名 · 增量字段' },
      { source_field: 'pay_type', source_type: 'VARCHAR(16)', target_field: 'pay_type', target_type: 'VARCHAR(16)' },
      { source_field: 'channel', source_type: 'VARCHAR(16)', target_field: 'channel', target_type: 'VARCHAR(16)' },
      { source_field: 'discount', source_type: 'DECIMAL(5,2)', target_field: 'discount', target_type: 'DECIMAL(5,2)' },
      { source_field: 'updated_at', source_type: 'DATETIME', target_field: 'updated_at', target_type: 'DATETIME' },
    ],
    masking_rules: [
      { field: 'email', rule: 'mask_email', description: '邮箱掩码', sample_before: 'zhangsan@gmail.com', sample_after: 'z***n@gmail.com', enforced: true },
      { field: 'phone', rule: 'mask_phone', description: '手机号掩码', sample_before: '13812345678', sample_after: '138****5678', enforced: true },
      { field: 'id_card', rule: 'mask_id_card', description: '证件号掩码', sample_before: '110101199003074512', sample_after: '1101**********12', enforced: true },
    ],
    quality_contract: {
      rules: [
        { code: 'E_NOT_POSITIVE', field: 'amount', expression: 'amount > 0', description: 'amount 必须为正', severity: 'blocking' },
        { code: 'E_NOT_NULL', field: 'order_no', expression: 'order_no IS NOT NULL', description: 'order_no 非空', severity: 'blocking' },
        { code: 'E_NOT_NULL', field: 'email', expression: 'email IS NOT NULL', description: 'email 非空', severity: 'blocking' },
      ],
    },
  },
  hocon: `env {
  parallelism = 2
  job.mode = "BATCH"
}

source {
  Jdbc {
    plugin_output = "mysql_orders"
    url = "jdbc:mysql://10.0.4.12:3306/trade"
    query = "SELECT * FROM orders WHERE created_at > \${watermark}"
  }
}

transform {
  Sql {
    plugin_input = "mysql_orders"
    query = "SELECT *, mask_email(email) FROM t WHERE status <> 'refunded'"
  }
}

sink {
  Doris {
    fenodes = "doris-fe:8030"
    table = "raw_orders_shadow"
  }
}
`,
  dag: {
    nodes: [
      { id: 'n1', label: 'MySQL 源表', kind: 'source', sub: 'orders · 8 字段' },
      { id: 'n2', label: '字段映射 / 脱敏', kind: 'transform', sub: '12 字段 · 3 条规则' },
      { id: 'n3', label: '受管SQL 质量过滤', kind: 'transform', sub: "status <> 'refunded'", detail: "SELECT * FROM orders WHERE status <> 'refunded' AND email IS NOT NULL · 由 Harness 沙箱执行，禁止 DDL/DML 写操作" },
      { id: 'n4', label: 'Doris raw 表', kind: 'sink', sub: 'raw_orders_shadow' },
      { id: 'n5', label: '原子 Swap', kind: 'publish', sub: '行数一致 → 正式表' },
    ],
    edges: [
      { from: 'n1', to: 'n2' },
      { from: 'n2', to: 'n3' },
      { from: 'n3', to: 'n4' },
      { from: 'n4', to: 'n5' },
    ],
  },
  gate_report: {
    passed: true,
    total: 6,
    passed_count: 6,
    findings: [
      { code: 'GATE_SCHEMA', name: 'Schema 一致性', status: 'passed', blocking: true },
      { code: 'GATE_MASKING', name: '脱敏覆盖', status: 'passed', blocking: true },
      { code: 'GATE_BUDGET', name: '预算阈值', status: 'passed', blocking: true },
      { code: 'GATE_ROWCOUNT', name: '行数硬判据', status: 'passed', blocking: true },
      { code: 'GATE_ROLLBACK', name: '回滚方案', status: 'passed', blocking: true },
      { code: 'GATE_PERMISSION', name: '权限', status: 'passed', blocking: true },
    ],
  },
}

/* ---------- 准备单 ---------- */

export const preparations: Preparation[] = [
  {
    id: 42, code: 'PR-018', version_id: 42, pipeline_id: 7, pipeline_name: 'orders 每日增量同步',
    status: 'pending', maker_id: 2, maker_name: '张伟',
    expires_at: isoIn(3 * DAY),
    input_fingerprint: 'b7e2c94a1f6038d5aa19c77e04f2b3d8915e6f0a2c4d8b1e3f5a7c9e0d2f4b6a8c',
    resource_scope: { source: ['mysql:trade.orders'], target: ['doris:raw_orders'] },
    impact_json: { write_tables: ['raw_orders'], estimated_rows: 1_204_332 },
    data_classification: 'internal',
    budget_json: { max_credits: 300, max_duration_seconds: 1800, max_read_rows: 1_500_000, max_write_bytes: 1_073_741_824 },
    rollback_plan_json: { steps: ['drop_shadow', 'restore_state'] },
    risk_level: 'P1',
    approval_requests: [
      { id: 91, preparation_id: 42, required_role: 'checker1', status: 'pending' },
      { id: 92, preparation_id: 42, required_role: 'checker2', status: 'pending' },
    ],
    created_at: daysAgo(1, 10),
  },
  {
    id: 41, code: 'PR-017', version_id: 42, pipeline_id: 8, pipeline_name: 'user_center 全量归档',
    status: 'pending', maker_id: 3, maker_name: '李娜',
    expires_at: isoIn(2 * DAY),
    input_fingerprint: 'c3d1e5f7092b4a6c8d0e2f4a6b8c0d1e3f5a7b9c2d4e6f8a0b1c3d5e7f9a0b2c4d',
    resource_scope: { source: ['postgresql:user_center.users'], target: ['doris:ods_users'] },
    impact_json: { write_tables: ['ods_users'], estimated_rows: 86_400 },
    data_classification: 'confidential',
    budget_json: { max_credits: 120, max_duration_seconds: 900 },
    rollback_plan_json: { steps: ['drop_shadow'] },
    risk_level: 'P2',
    approval_requests: [
      { id: 89, preparation_id: 41, required_role: 'checker1', status: 'decided', decision: 'approve', approver_id: 2, approver_name: '张伟', comment: '映射与脱敏核对无误', decided_at: daysAgo(1, 15) },
      { id: 90, preparation_id: 41, required_role: 'checker2', status: 'pending' },
    ],
    created_at: daysAgo(2, 11),
  },
  {
    id: 40, code: 'PR-016', version_id: 42, pipeline_id: 7, pipeline_name: 'oracle_finance 对账',
    status: 'rejected', maker_id: 4, maker_name: '王强',
    expires_at: daysAgo(1),
    input_fingerprint: 'd4e6f8a0b2c4d6e8f0a1c3e5a7b9d1f3a5b7c9d1e3f5a7b9c1d3e5f7a9b1d3f5a7b9',
    resource_scope: { source: ['oracle:FINDB.GL_BALANCE'], target: ['doris:ods_gl_balance'] },
    impact_json: { write_tables: ['ods_gl_balance'], estimated_rows: 2_300_000 },
    data_classification: 'secret',
    budget_json: { max_credits: 800, max_duration_seconds: 3600 },
    rollback_plan_json: { steps: ['drop_shadow', 'restore_state', 'notify_owner'] },
    risk_level: 'P0',
    approval_requests: [
      { id: 87, preparation_id: 40, required_role: 'checker1', status: 'decided', decision: 'approve', approver_id: 3, approver_name: '李娜', comment: '字段映射无误', decided_at: daysAgo(3, 14) },
      { id: 88, preparation_id: 40, required_role: 'checker2', status: 'decided', decision: 'reject', approver_id: 2, approver_name: '张伟', comment: '源库当前不可达，且缺少回滚演练记录', decided_at: daysAgo(3, 16) },
    ],
    created_at: daysAgo(4, 9),
  },
]

/* ---------- 执行运行（静态终态；进行中的 RUN-8801 由 db.ts 动态推进） ---------- */

export const runs: ExecutionRun[] = [
  {
    id: 8801, version_id: 42, pipeline_id: 7, pipeline_name: 'orders 每日增量同步', preparation_id: 42,
    run_kind: 'execute', status: 'running', sub_stage: 'COPYING', engine_job_id: 'st-job-8f21',
    input_records: 0, output_records: 0, error_records: 0, bytes_processed: 0,
    started_at: null, finished_at: null, diagnosis: null, quality_report: null, created_at: daysAgo(0, 9),
  },
  {
    id: 8800, version_id: 42, pipeline_id: 7, pipeline_name: 'orders 每日增量同步', preparation_id: 42,
    run_kind: 'execute', status: 'succeeded', engine_job_id: 'st-job-8e02',
    input_records: 1_204_332, output_records: 1_204_100, error_records: 232, bytes_processed: 618_618_880,
    started_at: daysAgo(1, 2), finished_at: daysAgo(1, 3), diagnosis: null,
    quality_report: {
      row_count_check: 'passed',
      error_code_distribution: { E_NOT_POSITIVE: 164, E_NOT_NULL: 68 },
      contract_hits: { not_null: 1_204_264, positive: 1_204_100 },
    },
    created_at: daysAgo(1, 2),
  },
  {
    id: 8799, version_id: 42, pipeline_id: 7, pipeline_name: 'orders 每日增量同步', preparation_id: 42,
    run_kind: 'execute', status: 'failed', engine_job_id: 'st-job-8d77',
    input_records: 1_204_332, output_records: 1_203_620, error_records: 480, bytes_processed: 617_900_032,
    started_at: daysAgo(2, 2), finished_at: daysAgo(2, 2),
    diagnosis: {
      root_cause: 'row_count_check failed：output(1,203,620) + error(480) ≠ input(1,204,332)，缺 232 行；源端在 COPY 阶段发生主键冲突重试导致丢行。',
      suggestions: [
        '检查源表 orders 在窗口期内的主键冲突日志',
        '将源端读取隔离级别调整为 REPEATABLE READ 后安全重跑',
        '确认 shadow 表无主键重复残留后可发起 rerun',
      ],
    },
    quality_report: {
      row_count_check: 'failed',
      error_code_distribution: { E_NOT_POSITIVE: 380, E_NOT_NULL: 100 },
      contract_hits: { not_null: 1_204_232, positive: 1_203_952 },
    },
    created_at: daysAgo(2, 2),
  },
  {
    id: 8798, version_id: 42, pipeline_id: 8, pipeline_name: 'user_center 全量归档', preparation_id: 41,
    run_kind: 'execute', status: 'succeeded', engine_job_id: 'st-job-8c41',
    input_records: 86_400, output_records: 86_400, error_records: 0, bytes_processed: 44_236_800,
    started_at: daysAgo(3, 2), finished_at: daysAgo(3, 3), diagnosis: null,
    quality_report: { row_count_check: 'passed', error_code_distribution: {}, contract_hits: { not_null: 86_400 } },
    created_at: daysAgo(3, 2),
  },
  {
    id: 8797, version_id: 42, pipeline_id: 9, pipeline_name: 'refund 明细清洗', preparation_id: null,
    run_kind: 'dry_run', status: 'cancelled', engine_job_id: 'st-job-8b19',
    input_records: 1_000, output_records: 940, error_records: 60, bytes_processed: 512_000,
    started_at: daysAgo(4, 15), finished_at: daysAgo(4, 15), diagnosis: null,
    quality_report: {
      row_count_check: 'passed',
      error_code_distribution: { E_NOT_POSITIVE: 44, E_NOT_NULL: 16 },
      contract_hits: { not_null: 984, positive: 940 },
    },
    created_at: daysAgo(4, 14),
  },
  {
    id: 8796, version_id: 42, pipeline_id: 10, pipeline_name: 'dim_region 维表同步', preparation_id: null,
    run_kind: 'execute', status: 'succeeded', engine_job_id: 'st-job-8a07',
    input_records: 3_742, output_records: 3_742, error_records: 0, bytes_processed: 1_916_000,
    started_at: daysAgo(5, 6), finished_at: daysAgo(5, 6), diagnosis: null,
    quality_report: { row_count_check: 'passed', error_code_distribution: {}, contract_hits: {} },
    created_at: daysAgo(5, 6),
  },
  {
    id: 8795, version_id: 42, pipeline_id: 11, pipeline_name: 'crm_contract 抽取', preparation_id: null,
    run_kind: 'execute', status: 'failed', engine_job_id: 'st-job-89f0',
    input_records: 52_010, output_records: 0, error_records: 52_010, bytes_processed: 26_600_000,
    started_at: daysAgo(6, 22), finished_at: daysAgo(6, 23),
    diagnosis: {
      root_cause: '目标 ClickHouse 表 contract 字段精度不匹配（DECIMAL(18,4) → DECIMAL(10,2) 溢出）。',
      suggestions: ['在字段映射中将 amount 目标类型改为 DECIMAL(18,4)', '重新触发 Dry-Run 验证后再次提交'],
    },
    quality_report: {
      row_count_check: 'failed',
      error_code_distribution: { E_NOT_POSITIVE: 52_010 },
      contract_hits: { positive: 0 },
    },
    created_at: daysAgo(6, 21),
  },
]

/* ---------- Benchmark ---------- */

const baseMetrics = {
  compile_pass_rate: 0.924,
  field_f1: 0.89,
  dry_run_pass_rate: 0.88,
  block_rate: 1.0,
  false_positive_rate: 0.032,
  health_score: 94,
}

export const benchmarks: BenchmarkRun[] = [
  { id: 9, suite_version: 'v1.0', status: 'succeeded', metrics_json: { ...baseMetrics }, started_at: daysAgo(1, 4), finished_at: daysAgo(1, 5) },
  { id: 8, suite_version: 'v1.0', status: 'succeeded', metrics_json: { ...baseMetrics, field_f1: 0.87, health_score: 92.6 }, started_at: daysAgo(2, 4), finished_at: daysAgo(2, 5) },
  { id: 7, suite_version: 'v1.0', status: 'succeeded', metrics_json: { ...baseMetrics, compile_pass_rate: 0.91, health_score: 91.8 }, started_at: daysAgo(3, 4), finished_at: daysAgo(3, 5) },
  { id: 6, suite_version: 'v1.0', status: 'succeeded', metrics_json: { ...baseMetrics, health_score: 93.1 }, started_at: daysAgo(4, 4), finished_at: daysAgo(4, 5) },
  { id: 5, suite_version: 'v0.9', status: 'failed', metrics_json: null, started_at: daysAgo(5, 4), finished_at: daysAgo(5, 5) },
  { id: 4, suite_version: 'v1.0', status: 'succeeded', metrics_json: { ...baseMetrics, false_positive_rate: 0.041, health_score: 90.7 }, started_at: daysAgo(6, 4), finished_at: daysAgo(6, 5) },
  { id: 3, suite_version: 'v1.0', status: 'succeeded', metrics_json: { ...baseMetrics, health_score: 92.2 }, started_at: daysAgo(7, 4), finished_at: daysAgo(7, 5) },
  { id: 2, suite_version: 'v0.9', status: 'succeeded', metrics_json: { ...baseMetrics, compile_pass_rate: 0.88, health_score: 89.5 }, started_at: daysAgo(8, 4), finished_at: daysAgo(8, 5) },
  { id: 1, suite_version: 'v0.9', status: 'succeeded', metrics_json: { ...baseMetrics, field_f1: 0.84, health_score: 88.3 }, started_at: daysAgo(9, 4), finished_at: daysAgo(9, 5) },
  { id: 10, suite_version: 'v1.0', status: 'succeeded', metrics_json: { ...baseMetrics, health_score: 93.6 }, started_at: daysAgo(0, 3), finished_at: daysAgo(0, 4) },
]

/* ---------- 安全进化 ---------- */

export const candidates: EvolutionCandidate[] = [
  {
    id: 1, project_id: 1, kind: 'prompt', title: '生成提示词 v2.4.0-rc1', status: 'proposed',
    content_json: { template: '...新版 Schema 推理模板...' },
    health_before: 87.2, health_after: 91.8,
    review_report_json: { benchmark_run_id: 9, findings: ['脱敏召回率提升 4.6pp', '无误报回归'] },
    created_by: 4, created_by_name: '王强', created_at: daysAgo(2, 16), updated_at: daysAgo(2, 16),
  },
  {
    id: 2, project_id: 1, kind: 'policy', title: '门禁阈值策略 v2.3.1', status: 'approved',
    content_json: { budget_hard_limit: 500 },
    health_before: 85, health_after: 88.4,
    review_report_json: { benchmark_run_id: 8, findings: ['拦截率保持 100%'] },
    created_by: 4, created_by_name: '王强', created_at: daysAgo(6, 11), updated_at: daysAgo(5, 10),
  },
  {
    id: 3, project_id: 1, kind: 'prompt', title: '生成提示词 v2.3.0', status: 'rejected',
    content_json: { template: '...旧模板...' },
    health_before: 90.1, health_after: 82.3,
    review_report_json: { benchmark_run_id: 4, findings: ['误报率上升至 7.8%，健康度回归'] },
    created_by: 4, created_by_name: '王强', created_at: daysAgo(9, 15), updated_at: daysAgo(8, 9),
  },
]

export const grayFlags: GrayFlag[] = [
  { project_id: 1, flag_key: 'schema_inference_v2', enabled: true, description: '启用新版 Schema 推理', impact_scope: '元数据探查 / 字段映射生成', updated_by: 4, updated_at: daysAgo(3, 12) },
  { project_id: 1, flag_key: 'llm_intent_check', enabled: true, description: '启用 LLM 意图校验', impact_scope: '生成前置意图审查', updated_by: 4, updated_at: daysAgo(4, 12) },
  { project_id: 1, flag_key: 'shadow_dual_write', enabled: false, description: '影子表双写校验', impact_scope: '执行期 shadow 表对账', updated_by: 4, updated_at: daysAgo(5, 12) },
  { project_id: 1, flag_key: 'strict_budget_breaker', enabled: false, description: '严格预算熔断', impact_scope: '监督守护 breach 动作', updated_by: 4, updated_at: daysAgo(6, 12) },
]

/* ---------- 审计事件（~240 条链式生成，列表 total 报 1384） ---------- */

const AUDIT_TYPES = [
  'run.start',
  'preparation.submit',
  'preparation.freeze',
  'approval.reject',
  'token.issue',
  'run.fail',
  'config.change',
  'run.succeed',
  'approval.approve',
  'connection.test',
]

const AUDIT_SUMMARIES: Record<string, string> = {
  'run.start': '启动执行运行 RUN-{n}',
  'preparation.submit': '提交审批 PR-{n}',
  'preparation.freeze': '冻结准备单 PR-{n}',
  'approval.reject': '审批拒绝 PR-{n}：回滚演练记录缺失',
  'token.issue': '签发一次性 Capability 令牌',
  'run.fail': '运行失败 RUN-{n}：row_count_check failed',
  'config.change': '配置变更：更新连接掩码凭据',
  'run.succeed': '运行成功 RUN-{n}',
  'approval.approve': '审批通过 PR-{n}',
  'connection.test': '连通性测试通过',
}

export function buildAuditEvents(): AuditEvent[] {
  const events: AuditEvent[] = []
  const start = new Date('2026-06-05T08:00:00Z').getTime()
  const end = new Date('2026-06-12T22:00:00Z').getTime()
  const span = end - start
  let prev = 'GENESIS'
  for (let i = 1; i <= 240; i++) {
    const ts = new Date(start + (span * i) / 240).toISOString()
    const type = AUDIT_TYPES[i % AUDIT_TYPES.length]
    const actor = users[i % users.length]
    const summary = AUDIT_SUMMARIES[type].replace('{n}', String(40 + (i % 3)))
    const hash = demoHash(`${prev}|${i}|${type}|${ts}|${summary}`)
    events.push({
      id: 1000 + i,
      project_id: 1,
      event_type: type,
      actor_id: actor.id,
      actor_name: actor.display_name,
      resource_type: type.split('.')[0],
      resource_id: `BLK-${String(i).padStart(4, '0')}`,
      summary,
      prev_event_hash: prev,
      event_hash: hash,
      created_at: ts,
    })
    prev = hash
  }
  return events
}

/** 审计列表接口固定上报的总数（演示：账本远大于当前项目样本） */
export const AUDIT_TOTAL = 1384
