/** API 层统一出口 */
export * from './types'
export { ApiError, getToken, setToken, clearToken } from './client'
export { authApi } from './auth'
export { projectApi } from './projects'
export { connApi, fileApi } from './connections'
export type { ConnListParams, ConnTestResp } from './connections'
export { pipelineApi } from './pipelines'
export type { PipelineDetail } from './pipelines'
export { genApi } from './generation'
export { prepApi } from './preparations'
export { runApi } from './runs'
export { benchApi } from './benchmarks'
export { auditApi } from './audit'
export type { AuditQuery } from './audit'
export { evolutionApi } from './evolution'

import { get } from './client'
import type { HealthResp } from './types'

/** 健康检查（不属于 /api/v1，路径 /health） */
export function getHealth() {
  return get<HealthResp>('/health')
}
