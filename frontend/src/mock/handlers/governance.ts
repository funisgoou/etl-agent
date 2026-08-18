import { MockError, paginate, register } from '../router'
import { appendAudit, computeBenchmark, db } from '../db'

/* ---------- Benchmark ---------- */

register('POST', '/api/v1/benchmarks/run', (ctx) => {
  const id = db.seq.bench++
  db.benchmarks.unshift({
    id,
    suite_version: String(ctx.body?.suite_version ?? 'v1.0'),
    status: 'running',
    metrics_json: null,
    started_at: new Date().toISOString(),
  })
  db.benchInternals.set(id, { id, startedAt: Date.now() })
  appendAudit({ event_type: 'benchmark.run', summary: `触发 Benchmark 评测（suite ${ctx.body?.suite_version ?? 'v1.0'}）`, resource_type: 'benchmark', resource_id: String(id) })
  return { status: 202, data: { benchmark_run_id: id, status: 'running' } }
})

register('GET', '/api/v1/benchmarks/runs/:id', (ctx) => {
  const b = computeBenchmark(Number(ctx.params.id))
  if (!b) throw new MockError(404, 'E_NOT_FOUND', 'benchmark run 不存在')
  return b
})

// ASSUMED: 接口文档只有单查，治理页趋势图需要历史列表
register('GET', '/api/v1/benchmarks/runs', (ctx) => {
  const limit = Math.min(50, Number(ctx.query.get('limit') ?? 10) || 10)
  return db.benchmarks.map((b) => computeBenchmark(b.id) ?? b).slice(0, limit)
})

/* ---------- 安全进化 ---------- */

register('GET', '/api/v1/evolution/candidates', (ctx) => {
  let list = db.candidates
  const status = ctx.query.get('status')
  if (status) list = list.filter((c) => c.status === status)
  return paginate(list, ctx.query)
})

register('POST', '/api/v1/evolution/candidates', (ctx) => {
  const body = ctx.body ?? {}
  const candidate = {
    id: db.seq.candidate++,
    project_id: Number(body.project_id ?? 1),
    kind: body.kind === 'policy' ? ('policy' as const) : ('prompt' as const),
    title: String(body.title ?? '未命名候选'),
    content_json: body.content_json ?? {},
    status: 'proposed' as const,
    created_by: 2,
    created_by_name: '张伟',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }
  db.candidates.unshift(candidate)
  appendAudit({ event_type: 'evolution.propose', summary: `提交安全进化候选 ${candidate.title}`, project_id: candidate.project_id, resource_type: 'evolution', resource_id: String(candidate.id) })
  return { status: 201, data: candidate }
})

register('GET', '/api/v1/evolution/candidates/:id', (ctx) => {
  const c = db.candidates.find((x) => x.id === Number(ctx.params.id))
  if (!c) throw new MockError(404, 'E_NOT_FOUND', '候选不存在')
  return c
})

register('POST', '/api/v1/evolution/candidates/:id/reviews', (ctx) => {
  const c = db.candidates.find((x) => x.id === Number(ctx.params.id))
  if (!c) throw new MockError(404, 'E_NOT_FOUND', '候选不存在')
  const decision = ctx.body?.decision
  if (decision !== 'approve' && decision !== 'reject') throw new MockError(400, 'E_VALID_DECISION', 'decision 必须为 approve|reject')
  c.status = decision === 'approve' ? 'approved' : 'rejected'
  c.review_report_json = ctx.body?.review_report_json ?? c.review_report_json
  c.updated_at = new Date().toISOString()
  appendAudit({ event_type: 'evolution.review', summary: `评审候选 ${c.title}：${decision === 'approve' ? '通过' : '拒绝'}`, project_id: c.project_id, resource_type: 'evolution', resource_id: String(c.id) })
  return c
})

register('GET', '/api/v1/evolution/gray-flags', (ctx) => {
  const pid = Number(ctx.query.get('project_id') ?? 1)
  return db.grayFlags.filter((f) => f.project_id === pid)
})

register('PUT', '/api/v1/evolution/gray-flags', (ctx) => {
  const body = ctx.body ?? {}
  const pid = Number(body.project_id ?? 1)
  const flag = db.grayFlags.find((f) => f.project_id === pid && f.flag_key === body.flag_key)
  if (!flag) throw new MockError(404, 'E_NOT_FOUND', '灰度开关不存在')
  // E_EVOLUTION_GATE：enabled=true 前置 —— 最新成功 benchmark health_score 须 > 90
  if (body.enabled === true) {
    const latest = db.benchmarks
      .map((b) => computeBenchmark(b.id) ?? b)
      .filter((b) => b.status === 'succeeded' && b.metrics_json)
      .sort((a, z) => z.id - a.id)[0]
    const score = latest?.metrics_json?.health_score ?? 0
    if (score <= 90) {
      throw new MockError(409, 'E_EVOLUTION_GATE', `灰度开启前置未满足：最新成功 Benchmark 健康度 ${score}（须 > 90）`, {
        benchmark_run_id: latest?.id,
        health_score: score,
      })
    }
  }
  flag.enabled = body.enabled === true
  if (body.description) flag.description = String(body.description)
  flag.updated_by = 2
  flag.updated_at = new Date().toISOString()
  appendAudit({ event_type: 'evolution.gray_flag', summary: `${flag.enabled ? '开启' : '关闭'}灰度开关 ${flag.flag_key}`, project_id: pid, resource_type: 'gray_flag', resource_id: flag.flag_key })
  return flag
})
