import { get, post } from './client'
import type { GlobalRole, Member, Page, Project, RoleGrant, RoleSlot } from './types'

export const projectApi = {
  list(params?: { page?: number; page_size?: number }) {
    return get<Page<Project>>('/projects', params)
  },
  create(payload: { name: string; code: string; description?: string }) {
    return post<Project>('/projects', payload)
  },
  get(projectId: number | string) {
    return get<Project>(`/projects/${projectId}`)
  },
  // ASSUMED: 接口文档只有 POST members，原型「成员与资格」抽屉需要成员列表
  listMembers(projectId: number | string) {
    return get<Member[]>(`/projects/${projectId}/members`)
  },
  addMember(projectId: number | string, payload: { user_id: number; role: GlobalRole }) {
    return post<Member>(`/projects/${projectId}/members`, payload)
  },
  listRoleGrants(projectId: number | string) {
    return get<RoleGrant[]>(`/projects/${projectId}/role-grants`)
  },
  grantRole(projectId: number | string, payload: { user_id: number; role_slot: RoleSlot }) {
    return post<RoleGrant>(`/projects/${projectId}/role-grants`, payload)
  },
}
