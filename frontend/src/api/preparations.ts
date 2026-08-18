import { get, post } from './client'
import type { Page, Preparation } from './types'

export const prepApi = {
  /** Prepare：生成准备单（前置：版本已冻结） */
  create(versionId: number | string) {
    return post<Preparation>(`/versions/${versionId}/prepare`)
  },
  // ASSUMED: 接口文档无准备单列表，运行中心/审批视图需要按项目+状态查询
  list(projectId: number | string, params?: { status?: string; page?: number; page_size?: number }) {
    return get<Page<Preparation>>(`/projects/${projectId}/preparations`, params)
  },
  // ASSUMED: 接口文档无准备单单查，审批抽屉需要详情
  get(id: number | string) {
    return get<Preparation>(`/preparations/${id}`)
  },
  /** Approve：具名审批决策 */
  decide(approvalId: number | string, payload: { decision: 'approve' | 'reject'; comment?: string }) {
    return post<{ id: number; status: string; decision: string; audit_event_id: number }>(
      `/approval-requests/${approvalId}/decisions`,
      payload,
    )
  },
  /** Commit：校验审批与指纹，签发 Capability 并提交执行 */
  commit(preparationId: number | string) {
    return post<{
      execution_run_id: number
      status: string
      capability_issued: boolean
      audit_event_id: number
    }>(`/preparations/${preparationId}/commit`)
  },
}
