import { get } from './client'
import type { AuditEvent, Page, VerifyResult } from './types'

export interface AuditQuery {
  project_id: number | string
  event_type?: string
  /** 关键词（匹配摘要/actor，ASSUMED 演示过滤参数） */
  keyword?: string
  from?: string
  to?: string
  page?: number
  page_size?: number
}

export const auditApi = {
  events(query: AuditQuery) {
    return get<Page<AuditEvent>>('/audit/events', query)
  },
  /** 重算证据账本哈希链并报告断点（D9） */
  verify(projectId: number | string) {
    return get<VerifyResult>('/audit/verify', { project_id: projectId })
  },
}
