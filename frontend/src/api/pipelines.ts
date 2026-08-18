import { get, post } from './client'
import type { Page, Pipeline, PipelineVersion } from './types'

/** Pipeline 详情（含版本数组） */
export interface PipelineDetail extends Pipeline {
  versions: PipelineVersion[]
}

export const pipelineApi = {
  list(projectId: number | string, params?: { page?: number; page_size?: number }) {
    return get<Page<Pipeline>>(`/projects/${projectId}/pipelines`, params)
  },
  create(payload: { project_id: number; name: string; code: string; description?: string }) {
    return post<Pipeline>('/pipelines', payload)
  },
  // ASSUMED: 接口文档无单查，Studio 页需要按 id 拉取 Pipeline + versions 数组
  get(pipelineId: number | string) {
    return get<PipelineDetail>(`/pipelines/${pipelineId}`)
  },
  createVersion(pipelineId: number | string, baseVersionId?: number) {
    return post<{ version_id: number; pipeline_id: number; version_number: number; status: string }>(
      `/pipelines/${pipelineId}/versions`,
      baseVersionId ? { base_version_id: baseVersionId } : {},
    )
  },
}
