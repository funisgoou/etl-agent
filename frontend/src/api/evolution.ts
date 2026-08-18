import { get, post, put } from './client'
import type { EvolutionCandidate, GrayFlag, Page } from './types'

export const evolutionApi = {
  listCandidates(params?: {
    project_id?: number | string
    status?: string
    page?: number
    page_size?: number
  }) {
    return get<Page<EvolutionCandidate>>('/evolution/candidates', params)
  },
  createCandidate(payload: {
    project_id: number
    kind: 'prompt' | 'policy'
    title: string
    content_json: Record<string, unknown>
  }) {
    return post<EvolutionCandidate>('/evolution/candidates', payload)
  },
  getCandidate(id: number | string) {
    return get<EvolutionCandidate>(`/evolution/candidates/${id}`)
  },
  review(
    id: number | string,
    payload: { decision: 'approve' | 'reject'; review_report_json?: Record<string, unknown> },
  ) {
    return post<EvolutionCandidate>(`/evolution/candidates/${id}/reviews`, payload)
  },
  listGrayFlags(projectId: number | string) {
    return get<GrayFlag[]>('/evolution/gray-flags', { project_id: projectId })
  },
  /** enabled=true 前置：最新成功 benchmark health_score > 90，否则 E_EVOLUTION_GATE */
  updateGrayFlag(payload: {
    project_id: number
    flag_key: string
    enabled: boolean
    description?: string
  }) {
    return put<GrayFlag>('/evolution/gray-flags', payload)
  },
}
