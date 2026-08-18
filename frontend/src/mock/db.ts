/**
 * Mock 内存数据库：全内存、刷新即重置。
 * 包含动态时间线推进逻辑（execute 17s / dry-run 6s / benchmark 5s / agent-run）。
 */
import type {
  AgentRun,
  AuditEvent,
  BenchmarkRun,
  ExecutionRun,
  QualityReport,
  SubStage,
} from '../api/types'
import * as seed from './data'

/* ---------- 运行时间线参数 ---------- */

/** execute 时间线：COPYING 0-8s → SPLITTING 8-14s → SWAPPING 14-17s → succeeded */
const EXEC = { copyEnd: 8, splitEnd: 14, swapEnd: 17, totalIn: 1_204_332, totalOut: 1_204_100, totalErr: 232 }
/** dry-run 时间线：pending 0-1s → COPYING 1-3s → SPLITTING 3-5s → succeeded(跳过 Swap) */
const DRY = { pendingEnd: 1, copyEnd: 3, splitEnd: 5, totalIn: 1_000, totalOut: 970, totalErr: 30 }

interface RunInternal {
  kind: 'execute' | 'dry_run'
  /** 时间线起点（ms epoch） */
  startedAt: number
  /** RUN-8801 首次访问时是否已重置过 started_at */
  touched: boolean
  /** 被 cancel/rollback 后锁死的终态 */
  forcedStatus?: 'cancelled' | 'rolled_back'
  forcedAt?: number
}

interface AgentRunInternal {
  id: number
  versionId: number
  startedAt: number
  answeredAt: number | null
}

interface BenchInternal {
  id: number
  startedAt: number
}

export interface Db {
  users: typeof seed.users
  projects: typeof seed.projects
  members: typeof seed.members
  roleGrants: typeof seed.roleGrants
  connections: typeof seed.connections
  profiles: typeof seed.profiles
  fileAssets: typeof seed.fileAssets
  pipelines: typeof seed.pipelines
  versions: typeof seed.versions
  preparations: typeof seed.preparations
  runs: ExecutionRun[]
  benchmarks: BenchmarkRun[]
  candidates: typeof seed.candidates
  grayFlags: typeof seed.grayFlags
  auditEvents: AuditEvent[]
  /** version 42 设计是否已生成完毕（agent-run succeeded 后置真） */
  designReady: boolean
  runInternals: Map<number, RunInternal>
  agentRuns: Map<number, AgentRunInternal>
  benchInternals: Map<number, BenchInternal>
  seq: Record<string, number>
}

function createDb(): Db {
  return {
    users: [...seed.users],
    projects: [...seed.projects],
    members: [...seed.members],
    roleGrants: [...seed.roleGrants],
    connections: [...seed.connections],
    profiles: [...seed.profiles],
    fileAssets: [...seed.fileAssets],
    pipelines: [...seed.pipelines],
    versions: [...seed.versions],
    preparations: JSON.parse(JSON.stringify(seed.preparations)),
    runs: JSON.parse(JSON.stringify(seed.runs)),
    benchmarks: JSON.parse(JSON.stringify(seed.benchmarks)),
    candidates: JSON.parse(JSON.stringify(seed.candidates)),
    grayFlags: JSON.parse(JSON.stringify(seed.grayFlags)),
    auditEvents: seed.buildAuditEvents().reverse(), // 新→旧
    designReady: false,
    runInternals: new Map([[8801, { kind: 'execute', startedAt: Date.now(), touched: false }]]),
    agentRuns: new Map(),
    benchInternals: new Map(),
    seq: { agentRun: 11, run: 8802, bench: 11, prep: 43, approval: 93, pipeline: 12, version: 43, conn: 7, profile: 8, file: 9, candidate: 4, grant: 8, audit: 2000 },
  }
}

export const db: Db = createDb()

export function nextId(key: keyof Db['seq']): number {
  return db.seq[key]++
}

/* ---------- 账本 ---------- */

/** 所有写操作向审计列表头插一条事件（简易链式哈希） */
export function appendAudit(partial: {
  event_type: string
  summary: string
  project_id?: number
  resource_type?: string
  resource_id?: string
}): AuditEvent {
  const head = db.auditEvents[0]
  const prev = head ? head.event_hash : 'GENESIS'
  const id = nextId('audit')
  const hash = seed.demoHash(`${prev}|${id}|${partial.event_type}|${Date.now()}`)
  const evt: AuditEvent = {
    id,
    project_id: partial.project_id ?? 1,
    event_type: partial.event_type,
    actor_id: seed.currentUser.id,
    actor_name: seed.currentUser.display_name,
    resource_type: partial.resource_type,
    resource_id: partial.resource_id,
    summary: partial.summary,
    prev_event_hash: prev,
    event_hash: hash,
    created_at: new Date().toISOString(),
  }
  db.auditEvents.unshift(evt)
  return evt
}

/* ---------- 运行时间线推进 ---------- */

const TERMINAL: ReadonlySet<string> = new Set(['succeeded', 'failed', 'cancelled', 'rolled_back'])

function liveQuality(progress: number): QualityReport {
  return {
    row_count_check: 'pending',
    error_code_distribution: {
      E_NOT_POSITIVE: Math.floor(EXEC.totalErr * 0.7 * progress),
      E_NOT_NULL: Math.floor(EXEC.totalErr * 0.3 * progress),
    },
    contract_hits: {
      not_null: Math.floor(EXEC.totalIn * progress),
      positive: Math.floor(EXEC.totalOut * progress),
    },
  }
}

function finalizeExecute(base: ExecutionRun, startedAtMs: number): ExecutionRun {
  return {
    ...base,
    status: 'succeeded',
    sub_stage: null,
    input_records: EXEC.totalIn,
    output_records: EXEC.totalOut,
    error_records: EXEC.totalErr,
    bytes_processed: 618_618_880,
    started_at: new Date(startedAtMs).toISOString(),
    finished_at: new Date(startedAtMs + EXEC.swapEnd * 1000).toISOString(),
    quality_report: {
      row_count_check: 'passed',
      error_code_distribution: { E_NOT_POSITIVE: 164, E_NOT_NULL: 68 },
      contract_hits: { not_null: 1_204_264, positive: 1_204_100 },
    },
  }
}

function finalizeDry(base: ExecutionRun, startedAtMs: number): ExecutionRun {
  return {
    ...base,
    status: 'succeeded',
    sub_stage: null,
    input_records: DRY.totalIn,
    output_records: DRY.totalOut,
    error_records: DRY.totalErr,
    bytes_processed: 512_000,
    started_at: new Date(startedAtMs).toISOString(),
    finished_at: new Date(startedAtMs + DRY.splitEnd * 1000).toISOString(),
    quality_report: {
      row_count_check: 'passed',
      error_code_distribution: { E_NOT_POSITIVE: 21, E_NOT_NULL: 9 },
      contract_hits: { not_null: 991, positive: 970 },
    },
  }
}

/** 计算某 run 的当前状态（含动态时间线推进） */
export function computeRun(id: number): ExecutionRun | undefined {
  const base = db.runs.find((r) => r.id === id)
  if (!base) return undefined
  const internal = db.runInternals.get(id)
  if (!internal) return base

  // RUN-8801 首次被访问时把 started_at 重置为 now-3s，保证演示总能看到实时推进
  if (id === 8801 && !internal.touched && !internal.forcedStatus) {
    internal.startedAt = Date.now() - 3000
    internal.touched = true
  }

  if (internal.forcedStatus) {
    return {
      ...base,
      status: internal.forcedStatus,
      sub_stage: null,
      finished_at: new Date(internal.forcedAt ?? Date.now()).toISOString(),
    }
  }

  const t = (Date.now() - internal.startedAt) / 1000
  const startedIso = new Date(internal.startedAt).toISOString()

  if (internal.kind === 'dry_run') {
    if (t < DRY.pendingEnd) return { ...base, status: 'pending', sub_stage: null, started_at: startedIso }
    if (t < DRY.copyEnd) {
      const p = (t - DRY.pendingEnd) / (DRY.copyEnd - DRY.pendingEnd)
      return { ...base, status: 'running', sub_stage: 'COPYING', input_records: Math.floor(DRY.totalIn * p), bytes_processed: Math.floor(512_000 * p), started_at: startedIso, quality_report: liveQuality(p) }
    }
    if (t < DRY.splitEnd) {
      const p = (t - DRY.copyEnd) / (DRY.splitEnd - DRY.copyEnd)
      return { ...base, status: 'running', sub_stage: 'SPLITTING', input_records: DRY.totalIn, output_records: Math.floor(DRY.totalOut * p), error_records: Math.floor(DRY.totalErr * p), bytes_processed: 512_000, started_at: startedIso, quality_report: liveQuality(p) }
    }
    return finalizeDry(base, internal.startedAt)
  }

  // execute 时间线
  if (t < 0) return { ...base, status: 'pending', sub_stage: null, started_at: startedIso }
  if (t < EXEC.copyEnd) {
    const p = t / EXEC.copyEnd
    return { ...base, status: 'running', sub_stage: 'COPYING', input_records: Math.floor(EXEC.totalIn * p), bytes_processed: Math.floor(618_618_880 * p), started_at: startedIso, quality_report: liveQuality(p) }
  }
  if (t < EXEC.splitEnd) {
    const p = (t - EXEC.copyEnd) / (EXEC.splitEnd - EXEC.copyEnd)
    return {
      ...base,
      status: 'running',
      sub_stage: 'SPLITTING',
      input_records: EXEC.totalIn,
      output_records: Math.floor(EXEC.totalOut * p),
      error_records: Math.floor(EXEC.totalErr * p),
      bytes_processed: 618_618_880,
      started_at: startedIso,
      quality_report: liveQuality(p),
    }
  }
  if (t < EXEC.swapEnd) {
    return {
      ...base,
      status: 'running',
      sub_stage: 'SWAPPING' as SubStage,
      input_records: EXEC.totalIn,
      output_records: EXEC.totalOut,
      error_records: EXEC.totalErr,
      bytes_processed: 618_618_880,
      started_at: startedIso,
      quality_report: liveQuality(1),
    }
  }
  return finalizeExecute(base, internal.startedAt)
}

/** 列表：动态 run 也一并展开为当前状态 */
export function computeRuns(): ExecutionRun[] {
  return db.runs.map((r) => computeRun(r.id) ?? r)
}

export function isTerminal(status: string): boolean {
  return TERMINAL.has(status)
}

/* ---------- Agent-run 状态机 ---------- */

const AGENT_STEPS_RUNNING = [
  { name: '意图解析', status: 'done' as const, detail: '已确认增量同步意图' },
  { name: '元数据探查', status: 'done' as const, detail: 'orders 表 8 字段 · 耗时 2.3s' },
  { name: '生成配置', status: 'running' as const, detail: 'SeaTunnel HOCON + 受管SQL' },
  { name: '门禁校验', status: 'pending' as const, detail: '6 项安全门禁' },
]

const AGENT_STEPS_DONE = AGENT_STEPS_RUNNING.map((s) => ({ ...s, status: 'done' as const }))

export function computeAgentRun(id: number): AgentRun | undefined {
  const ar = db.agentRuns.get(id)
  if (!ar) return undefined
  const now = Date.now()

  if (ar.answeredAt !== null) {
    const done = now - ar.answeredAt >= 2000
    if (done) db.designReady = true
    return {
      run_id: id,
      version_id: ar.versionId,
      status: done ? 'succeeded' : 'running',
      step_count: 4,
      steps: done ? AGENT_STEPS_DONE : AGENT_STEPS_RUNNING,
      pending_question: null,
    }
  }

  if (now - ar.startedAt < 2000) {
    return { run_id: id, version_id: ar.versionId, status: 'running', step_count: 4, steps: AGENT_STEPS_RUNNING, pending_question: null }
  }

  return {
    run_id: id,
    version_id: ar.versionId,
    status: 'waiting_input',
    step_count: 2,
    steps: AGENT_STEPS_RUNNING,
    pending_question: {
      message: '好的，我需要确认几个信息：\n1) 源表主键是什么？\n2) 增量字段是哪个？\n3) 退款订单的过滤条件是 status=\'refunded\' 吗？',
      // ASSUMED: interrupt 表单由后端 schema 驱动渲染（SPEC 8），接口文档未定义 fields 数组
      fields: [
        { key: 'primary_key', label: '源表主键', type: 'text', value: 'id', required: true },
        { key: 'incremental_field', label: '增量字段', type: 'select', options: ['created_at', 'updated_at', 'id'], value: 'created_at', required: true },
        { key: 'refund_filter', label: '退款过滤条件', type: 'text', value: "status='refunded'", placeholder: "如 status='refunded'", required: true },
      ],
    },
  }
}

/* ---------- Benchmark 动态 ---------- */

export function computeBenchmark(id: number): BenchmarkRun | undefined {
  const b = db.benchmarks.find((x) => x.id === id)
  if (!b) return undefined
  const internal = db.benchInternals.get(id)
  if (!internal) return b
  if (Date.now() - internal.startedAt < 5000) {
    return { ...b, status: 'running', metrics_json: null, started_at: new Date(internal.startedAt).toISOString(), finished_at: undefined }
  }
  return {
    ...b,
    status: 'succeeded',
    metrics_json: {
      compile_pass_rate: 0.931,
      field_f1: 0.9,
      dry_run_pass_rate: 0.89,
      block_rate: 1.0,
      false_positive_rate: 0.03,
      health_score: 94.6,
    },
    started_at: new Date(internal.startedAt).toISOString(),
    finished_at: new Date(internal.startedAt + 5000).toISOString(),
  }
}
