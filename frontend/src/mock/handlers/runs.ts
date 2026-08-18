import { MockError, paginate, register } from '../router'
import { appendAudit, computeRun, computeRuns, db, isTerminal } from '../db'

/* ---------- 执行运行查询 ---------- */

register('GET', '/api/v1/projects/:projectId/execution-runs', (ctx) => {
  void ctx.params.projectId
  let list = computeRuns()
  const status = ctx.query.get('status')
  if (status) list = list.filter((r) => r.status === status)
  return paginate(list, ctx.query)
})

register('GET', '/api/v1/execution-runs/:id', (ctx) => {
  const run = computeRun(Number(ctx.params.id))
  if (!run) throw new MockError(404, 'E_NOT_FOUND', '执行运行不存在')
  return run
})

/* ---------- 运维操作 ---------- */

register('POST', '/api/v1/execution-runs/:id/cancel', (ctx) => {
  const id = Number(ctx.params.id)
  const run = computeRun(id)
  if (!run) throw new MockError(404, 'E_NOT_FOUND', '执行运行不存在')
  if (isTerminal(run.status)) throw new MockError(409, 'E_RUN_INVALID_STATE', `run 已处于终态 ${run.status}`)
  const internal = db.runInternals.get(id)
  if (internal) {
    internal.forcedStatus = 'cancelled'
    internal.forcedAt = Date.now()
  } else {
    const base = db.runs.find((r) => r.id === id)
    if (base) base.status = 'cancelled'
  }
  const evt = appendAudit({ event_type: 'run.cancel', summary: `取消运行 RUN-${id}`, resource_type: 'execution_run', resource_id: String(id) })
  return { status: 202, data: { id, status: 'cancelled', audit_event_id: evt.id } }
})

register('POST', '/api/v1/execution-runs/:id/rollback', (ctx) => {
  const id = Number(ctx.params.id)
  const run = computeRun(id)
  if (!run) throw new MockError(404, 'E_NOT_FOUND', '执行运行不存在')
  const internal = db.runInternals.get(id)
  if (internal) {
    internal.forcedStatus = 'rolled_back'
    internal.forcedAt = Date.now()
  } else {
    const base = db.runs.find((r) => r.id === id)
    if (base) base.status = 'rolled_back'
  }
  const evt = appendAudit({ event_type: 'run.rollback', summary: `受管回滚 RUN-${id}（drop_shadow + restore_state）`, resource_type: 'execution_run', resource_id: String(id) })
  return { status: 202, data: { id, status: 'rolled_back', audit_event_id: evt.id } }
})

register('POST', '/api/v1/execution-runs/:id/rerun', (ctx) => {
  const id = Number(ctx.params.id)
  const run = computeRun(id)
  if (!run) throw new MockError(404, 'E_NOT_FOUND', '执行运行不存在')
  if (!isTerminal(run.status)) {
    throw new MockError(409, 'E_RUN_INVALID_STATE', '仅允许对终态 run 发起安全重跑（R6）')
  }
  const newId = db.seq.run++
  db.runs.unshift({
    ...run,
    id: newId,
    status: 'pending',
    sub_stage: null,
    engine_job_id: `st-job-${newId.toString(36)}`,
    input_records: 0,
    output_records: 0,
    error_records: 0,
    bytes_processed: 0,
    started_at: null,
    finished_at: null,
    diagnosis: null,
    quality_report: null,
    created_at: new Date().toISOString(),
  })
  db.runInternals.set(newId, { kind: run.run_kind === 'dry_run' ? 'dry_run' : 'execute', startedAt: Date.now(), touched: true })
  const evt = appendAudit({ event_type: 'run.rerun', summary: `安全重跑 RUN-${id} → RUN-${newId}（指纹一致）`, resource_type: 'execution_run', resource_id: String(newId) })
  return { status: 201, data: { execution_run_id: newId, rerun_of: id, audit_event_id: evt.id } }
})
