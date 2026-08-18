import { register } from '../router'
import { db } from '../db'
import { AUDIT_TOTAL } from '../data'

/* ---------- 审计事件列表（过滤 + 分页；total 固定报 1384） ---------- */

register('GET', '/api/v1/audit/events', (ctx) => {
  let list = db.auditEvents
  const type = ctx.query.get('event_type')
  if (type) list = list.filter((e) => e.event_type === type)
  const keyword = ctx.query.get('keyword')?.toLowerCase()
  if (keyword) {
    list = list.filter(
      (e) =>
        e.summary.toLowerCase().includes(keyword) ||
        (e.actor_name ?? '').toLowerCase().includes(keyword) ||
        (e.resource_id ?? '').toLowerCase().includes(keyword),
    )
  }
  const from = ctx.query.get('from')
  if (from) list = list.filter((e) => e.created_at >= from)
  const to = ctx.query.get('to')
  if (to) list = list.filter((e) => e.created_at <= to)

  const page = Math.max(1, Number(ctx.query.get('page') ?? 1) || 1)
  const pageSize = Math.min(100, Math.max(1, Number(ctx.query.get('page_size') ?? 20) || 20))
  const start = (page - 1) * pageSize
  // total 报 1384：演示「账本远大于当前可见样本」
  return { items: list.slice(start, start + pageSize), total: AUDIT_TOTAL, page, page_size: pageSize }
})

/* ---------- 账本哈希链校验（D9 篡改演示：固定断点 BLK-0042 / event 777） ---------- */

register('GET', '/api/v1/audit/verify', (ctx) => {
  void ctx.query.get('project_id')
  return {
    project_id: 1,
    ok: false,
    checked_events: AUDIT_TOTAL,
    broken_at_event_id: 777,
    expected_hash: 'c91a3f7e02b84d19',
    actual_hash: '44d0b2a6f18c90e3',
    // 演示备注：断点对应资源 BLK-0042（账本第 777 号事件被篡改）
    note: 'broken at BLK-0042',
  }
})
