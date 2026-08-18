import { MockError, paginate, register } from '../router'
import { appendAudit, computeRun, db, isTerminal } from '../db'
import { currentUser } from '../data'

/* ---------- 准备单查询 ---------- */

// ASSUMED: 接口文档无准备单列表，审批/运行中心视图需要
register('GET', '/api/v1/projects/:projectId/preparations', (ctx) => {
  void ctx.params.projectId // mock 不严格按项目隔离准备单（演示数据均属项目 1）
  let list = db.preparations
  const status = ctx.query.get('status')
  if (status) list = list.filter((p) => p.status === status)
  return paginate(list, ctx.query)
})

// ASSUMED: 接口文档无准备单单查，审批抽屉需要详情
register('GET', '/api/v1/preparations/:id', (ctx) => {
  const prep = db.preparations.find((p) => p.id === Number(ctx.params.id))
  if (!prep) throw new MockError(404, 'E_NOT_FOUND', '准备单不存在')
  return prep
})

/* ---------- Approve ---------- */

register('POST', '/api/v1/approval-requests/:id/decisions', (ctx) => {
  const id = Number(ctx.params.id)
  const body = ctx.body ?? {}
  const decision = body.decision as 'approve' | 'reject'
  if (decision !== 'approve' && decision !== 'reject') {
    throw new MockError(400, 'E_VALID_DECISION', 'decision 必须为 approve|reject')
  }

  for (const prep of db.preparations) {
    const ap = prep.approval_requests.find((a) => a.id === id)
    if (!ap) continue
    if (prep.status !== 'pending') {
      throw new MockError(409, 'E_PREP_FINALIZED', `准备单 ${prep.code} 已终结（${prep.status}）`)
    }
    if (ap.status === 'decided') {
      throw new MockError(409, 'E_PREP_DECIDED', '该审批请求已完成决策')
    }
    // D3 互斥演示：maker 不能自批
    if (prep.maker_id === currentUser.id) {
      throw new MockError(403, 'E_FORBIDDEN_DUTY', '申请人不能审批自己提交的准备单（自批禁止）', {
        preparation_id: prep.id,
        conflict_slot: ap.required_role,
      })
    }
    ap.status = 'decided'
    ap.decision = decision
    ap.approver_id = currentUser.id
    ap.approver_name = currentUser.display_name
    ap.comment = body.comment ?? ''
    ap.decided_at = new Date().toISOString()

    if (decision === 'reject') {
      prep.status = 'rejected'
    } else if (prep.approval_requests.every((a) => a.status === 'decided' && a.decision === 'approve')) {
      prep.status = 'approved'
    }
    const evt = appendAudit({
      event_type: decision === 'approve' ? 'approval.approve' : 'approval.reject',
      summary: `${currentUser.display_name} ${decision === 'approve' ? '通过' : '拒绝'} ${prep.code}（${ap.required_role}）`,
      resource_type: 'preparation',
      resource_id: String(prep.id),
    })
    return { id, status: 'decided', decision, approver_id: currentUser.id, decided_at: ap.decided_at, audit_event_id: evt.id }
  }
  throw new MockError(404, 'E_NOT_FOUND', '审批请求不存在')
})

/* ---------- Commit ---------- */

register('POST', '/api/v1/preparations/:id/commit', (ctx) => {
  const prep = db.preparations.find((p) => p.id === Number(ctx.params.id))
  if (!prep) throw new MockError(404, 'E_NOT_FOUND', '准备单不存在')
  if (prep.status !== 'approved') {
    throw new MockError(409, 'E_PREP_NOT_APPROVED', `审批未齐，当前状态 ${prep.status}`)
  }
  prep.status = 'committed'
  const runId = db.seq.run++
  db.runs.unshift({
    id: runId,
    version_id: prep.version_id,
    pipeline_id: prep.pipeline_id,
    pipeline_name: prep.pipeline_name,
    preparation_id: prep.id,
    run_kind: 'execute',
    status: 'pending',
    sub_stage: null,
    engine_job_id: `st-job-${runId.toString(36)}`,
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
  db.runInternals.set(runId, { kind: 'execute', startedAt: Date.now(), touched: true })
  const evt = appendAudit({
    event_type: 'token.issue',
    summary: `Commit ${prep.code}：签发单次 Capability，提交执行 RUN-${runId}`,
    resource_type: 'execution_run',
    resource_id: String(runId),
  })
  return { status: 201, data: { execution_run_id: runId, status: 'pending', capability_issued: true, audit_event_id: evt.id } }
})
