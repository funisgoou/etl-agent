import { get, post } from './client'
import type { ExecutionRun, Page, RunStatus } from './types'

/**
 * 执行运行 API。
 * 注意：SSE 实时流不走本模块，走 `@/sse/useRunStream`（EventSource 工厂见 mock/index.ts）。
 */
export const runApi = {
  list(projectId: number | string, params?: { status?: RunStatus; page?: number; page_size?: number }) {
    return get<Page<ExecutionRun>>(`/projects/${projectId}/execution-runs`, params)
  },
  get(id: number | string) {
    return get<ExecutionRun>(`/execution-runs/${id}`)
  },
  cancel(id: number | string) {
    return post<{ id: number; status: string; audit_event_id: number }>(`/execution-runs/${id}/cancel`)
  },
  rollback(id: number | string) {
    return post<{ id: number; status: string; audit_event_id: number }>(`/execution-runs/${id}/rollback`)
  },
  /** 安全重跑（R6）：仅终态 run，否则 E_RUN_INVALID_STATE */
  rerun(id: number | string) {
    return post<{ execution_run_id: number; rerun_of: number; audit_event_id: number }>(
      `/execution-runs/${id}/rerun`,
    )
  },
}
