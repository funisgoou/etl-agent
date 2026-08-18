import { del, get, post, put, upload } from './client'
import type { ConnType, Connection, FileAsset, Page, Profile } from './types'

export interface ConnListParams {
  page?: number
  page_size?: number
  conn_type?: ConnType
}

export interface ConnTestResp {
  ok: boolean
  latency_ms?: number
  server_version?: string
  message?: string
}

export const connApi = {
  list(projectId: number | string, params?: ConnListParams) {
    return get<Page<Connection>>(`/projects/${projectId}/connections`, params)
  },
  create(
    projectId: number | string,
    payload: { name: string; conn_type: ConnType; config_json: Record<string, unknown> },
  ) {
    return post<Connection>(`/projects/${projectId}/connections`, payload)
  },
  update(id: number, payload: Partial<{ name: string; config_json: Record<string, unknown> }>) {
    return put<Connection>(`/connections/${id}`, payload)
  },
  test(id: number) {
    return post<ConnTestResp>(`/connections/${id}/tests`)
  },
  createProfile(id: number, payload: { object_name: string; sample_size?: number }) {
    return post<Profile>(`/connections/${id}/profiles`, payload)
  },
  listProfiles(id: number, params?: { page?: number; page_size?: number }) {
    return get<Page<Profile>>(`/connections/${id}/profiles`, params)
  },
}

export const fileApi = {
  /** multipart：project_id + file */
  upload(projectId: number | string, file: File) {
    const fd = new FormData()
    fd.append('project_id', String(projectId))
    fd.append('file', file)
    return upload<FileAsset>('/file-assets', fd)
  },
  // ASSUMED: 接口文档只有上传，原型数据资产页需要文件资产列表
  list(projectId: number | string, params?: { page?: number; page_size?: number }) {
    return get<Page<FileAsset>>('/file-assets', { ...params, project_id: projectId })
  },
  // ASSUMED: 原型资产页需要删除文件资产
  remove(id: number) {
    return del<void>(`/file-assets/${id}`)
  },
}
