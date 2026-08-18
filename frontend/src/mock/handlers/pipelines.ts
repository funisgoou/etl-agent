import { MockError, paginate, register } from '../router'
import { appendAudit, computeAgentRun, db, nextId } from '../db'
import { design42 } from '../data'
import type { ExecutionRun, PipelineVersion } from '../../api/types'

/* ---------- Pipeline ---------- */

register('GET', '/api/v1/projects/:projectId/pipelines', (ctx) => {
  const list = db.pipelines.filter((p) => p.project_id === Number(ctx.params.projectId))
  return paginate(list, ctx.query)
})

register('POST', '/api/v1/pipelines', (ctx) => {
  const body = ctx.body ?? {}
  const pipeline = {
    id: nextId('pipeline'),
    project_id: Number(body.project_id ?? 1),
    name: String(body.name ?? '未命名 Pipeline'),
    code: String(body.code ?? `pipeline_${Date.now()}`),
    description: body.description ?? '',
    status: 'draft',
    created_at: new Date().toISOString(),
  }
  db.pipelines.push(pipeline)
  // 初始自动创建 version_number=1 草稿版本
  db.versions.push({
    id: nextId('version'),
    pipeline_id: pipeline.id,
    version_number: 1,
    label: 'v1.0-draft',
    status: 'draft',
    artifact_digest: null,
    base_version_id: null,
    created_at: new Date().toISOString(),
  })
  appendAudit({ event_type: 'pipeline.create', summary: `创建 Pipeline ${pipeline.name}`, project_id: pipeline.project_id, resource_type: 'pipeline', resource_id: String(pipeline.id) })
  return { status: 201, data: pipeline }
})

// ASSUMED: 接口文档无单查，Studio 页需要 Pipeline + versions 数组
register('GET', '/api/v1/pipelines/:id', (ctx) => {
  const pipeline = db.pipelines.find((p) => p.id === Number(ctx.params.id))
  if (!pipeline) throw new MockError(404, 'E_NOT_FOUND', 'Pipeline 不存在')
  const versions = db.versions.filter((v) => v.pipeline_id === pipeline.id)
  return { ...pipeline, versions }
})

register('POST', '/api/v1/pipelines/:id/versions', (ctx) => {
  const pid = Number(ctx.params.id)
  const existing = db.versions.filter((v) => v.pipeline_id === pid)
  if (!db.pipelines.some((p) => p.id === pid)) throw new MockError(404, 'E_NOT_FOUND', 'Pipeline 不存在')
  const version: PipelineVersion = {
    id: nextId('version'),
    pipeline_id: pid,
    version_number: Math.max(0, ...existing.map((v) => v.version_number)) + 1,
    label: undefined,
    status: 'draft',
    artifact_digest: null,
    base_version_id: ctx.body?.base_version_id ?? null,
    created_at: new Date().toISOString(),
  }
  db.versions.push(version)
  return {
    status: 201,
    data: {
      version_id: version.id,
      pipeline_id: pid,
      version_number: version.version_number,
      status: 'draft',
      base_version_id: version.base_version_id,
    },
  }
})

/* ---------- 生成（LangGraph 状态机演示） ---------- */

register('POST', '/api/v1/versions/:versionId/generation', (ctx) => {
  const versionId = Number(ctx.params.versionId)
  const id = nextId('agentRun')
  db.agentRuns.set(id, { id, versionId, startedAt: Date.now(), answeredAt: null })
  // 触发生成后旧设计失效，进入 generating
  db.designReady = false
  const v = db.versions.find((x) => x.id === versionId)
  if (v) v.status = 'generating'
  appendAudit({ event_type: 'generation.trigger', summary: `触发配置生成（version ${versionId}）`, resource_type: 'version', resource_id: String(versionId) })
  return { status: 202, data: { run_id: id, thread_id: `v${versionId}-01JMOCK${id}`, status: 'running' } }
})

register('GET', '/api/v1/agent-runs/:id', (ctx) => {
  const run = computeAgentRun(Number(ctx.params.id))
  if (!run) throw new MockError(404, 'E_NOT_FOUND', 'agent-run 不存在')
  return run
})

register('POST', '/api/v1/agent-runs/:id/answers', (ctx) => {
  const id = Number(ctx.params.id)
  const ar = db.agentRuns.get(id)
  if (!ar) throw new MockError(404, 'E_NOT_FOUND', 'agent-run 不存在')
  ar.answeredAt = Date.now()
  appendAudit({ event_type: 'generation.answer', summary: `提交澄清回答（agent-run ${id}）`, resource_type: 'agent_run', resource_id: String(id) })
  return { status: 202, data: { run_id: id, status: 'running' } }
})

register('GET', '/api/v1/versions/:versionId/design', (ctx) => {
  const versionId = Number(ctx.params.versionId)
  if (versionId === 42 && db.designReady) return design42
  // 生成前：仅部分字段
  return {
    version_id: versionId,
    status: 'generating',
    is_immutable: false,
    artifact_digest: null,
    etl_plan: {
      source: { kind: 'mysql', connection: 'mysql_prod_orders', table: 'orders' },
      target: { kind: 'doris', connection: 'doris_dw', table: 'raw_orders' },
      mappings: [],
      masking_rules: [],
      quality_contract: { rules: [] },
    },
  }
})

register('POST', '/api/v1/versions/:versionId/freeze', (ctx) => {
  const versionId = Number(ctx.params.versionId)
  const v = db.versions.find((x) => x.id === versionId)
  if (v) {
    v.status = 'frozen'
    v.artifact_digest = design42.artifact_digest
  }
  appendAudit({ event_type: 'version.freeze', summary: `冻结版本 v${versionId}（SHA256 已存证）`, resource_type: 'version', resource_id: String(versionId) })
  return { version_id: versionId, artifact_digest: design42.artifact_digest, is_immutable: true }
})

/* ---------- Dry-Run（免四眼，进账本） ---------- */

register('POST', '/api/v1/versions/:versionId/dry-run', (ctx) => {
  const versionId = Number(ctx.params.versionId)
  const id = nextId('run')
  const run: ExecutionRun = {
    id,
    version_id: versionId,
    pipeline_id: 7,
    pipeline_name: 'orders 每日增量同步',
    preparation_id: null,
    run_kind: 'dry_run',
    status: 'pending',
    sub_stage: null,
    engine_job_id: `st-job-${id.toString(36)}`,
    input_records: 0,
    output_records: 0,
    error_records: 0,
    bytes_processed: 0,
    started_at: null,
    finished_at: null,
    diagnosis: null,
    quality_report: null,
    created_at: new Date().toISOString(),
  }
  db.runs.unshift(run)
  db.runInternals.set(id, { kind: 'dry_run', startedAt: Date.now(), touched: true })
  const evt = appendAudit({ event_type: 'run.dry_run', summary: `发起 Dry-Run（version ${versionId}）`, resource_type: 'execution_run', resource_id: String(id) })
  return { status: 202, data: { execution_run_id: id, audit_event_id: evt.id, status: 'pending' } }
})

/* ---------- Prepare ---------- */

register('POST', '/api/v1/versions/:versionId/prepare', (ctx) => {
  const versionId = Number(ctx.params.versionId)
  const id = nextId('prep')
  const a1 = nextId('approval')
  const a2 = nextId('approval')
  const prep = {
    id,
    code: `PR-0${id}`,
    version_id: versionId,
    pipeline_id: 7,
    pipeline_name: 'orders 每日增量同步',
    status: 'pending' as const,
    maker_id: 2,
    maker_name: '张伟',
    expires_at: new Date(Date.now() + 3 * 86_400_000).toISOString(),
    input_fingerprint: 'b7e2c94a1f6038d5aa19c77e04f2b3d8915e6f0a2c4d8b1e3f5a7c9e0d2f4b6a8c',
    resource_scope: { source: ['mysql:trade.orders'], target: ['doris:raw_orders'] },
    impact_json: { write_tables: ['raw_orders'], estimated_rows: 1_204_332 },
    data_classification: 'internal',
    budget_json: { max_credits: 300, max_duration_seconds: 1800 },
    rollback_plan_json: { steps: ['drop_shadow', 'restore_state'] },
    risk_level: 'P1' as const,
    approval_requests: [
      { id: a1, preparation_id: id, required_role: 'checker1' as const, status: 'pending' as const },
      { id: a2, preparation_id: id, required_role: 'checker2' as const, status: 'pending' as const },
    ],
    created_at: new Date().toISOString(),
  }
  db.preparations.unshift(prep)
  const evt = appendAudit({ event_type: 'preparation.submit', summary: `生成准备单 ${prep.code}`, resource_type: 'preparation', resource_id: String(id) })
  return { status: 201, data: { ...prep, audit_event_id: evt.id } }
})
