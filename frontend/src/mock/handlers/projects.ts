import { MockError, paginate, register } from '../router'
import { appendAudit, db, nextId } from '../db'

/* ---------- 项目 ---------- */

register('GET', '/api/v1/projects', (ctx) => {
  return paginate(db.projects, ctx.query)
})

register('POST', '/api/v1/projects', (ctx) => {
  const body = ctx.body ?? {}
  if (!body.name || !body.code) throw new MockError(400, 'E_VALID_PROJECT', 'name 与 code 必填')
  const project = {
    id: Math.max(...db.projects.map((p) => p.id)) + 1,
    name: String(body.name),
    code: String(body.code),
    description: body.description ?? '',
    created_at: new Date().toISOString(),
    my_role: 'admin' as const,
  }
  db.projects.push(project)
  db.members.push({
    project_id: project.id,
    user_id: 2,
    username: 'zhangwei',
    display_name: '张伟',
    role: 'admin',
    joined_at: new Date().toISOString(),
  })
  appendAudit({ event_type: 'project.create', summary: `创建项目 ${project.name}`, project_id: project.id, resource_type: 'project', resource_id: String(project.id) })
  return { status: 201, data: project }
})

register('GET', '/api/v1/projects/:projectId', (ctx) => {
  const p = db.projects.find((x) => x.id === Number(ctx.params.projectId))
  if (!p) throw new MockError(404, 'E_NOT_FOUND', '项目不存在')
  return p
})

/* ---------- 成员与资格 ---------- */

// ASSUMED: 接口文档只有 POST members，此处补 GET 供「成员与资格」抽屉
register('GET', '/api/v1/projects/:projectId/members', (ctx) => {
  const pid = Number(ctx.params.projectId)
  return db.members.filter((m) => m.project_id === pid).map(({ project_id: _pid, ...rest }) => rest)
})

register('POST', '/api/v1/projects/:projectId/members', (ctx) => {
  const pid = Number(ctx.params.projectId)
  const body = ctx.body ?? {}
  if (!body.user_id || !body.role) throw new MockError(400, 'E_VALID_MEMBER', 'user_id 与 role 必填')
  const user = db.users.find((u) => u.id === Number(body.user_id))
  const member = {
    user_id: Number(body.user_id),
    username: user?.username ?? `user_${body.user_id}`,
    display_name: user?.display_name ?? `用户 ${body.user_id}`,
    role: body.role,
    joined_at: new Date().toISOString(),
  }
  if (!db.members.some((m) => m.project_id === pid && m.user_id === member.user_id)) {
    db.members.push({ project_id: pid, ...member })
  }
  appendAudit({ event_type: 'project.add_member', summary: `添加成员 ${member.display_name}（${member.role}）`, project_id: pid, resource_type: 'project', resource_id: String(pid) })
  return { status: 201, data: member }
})

register('GET', '/api/v1/projects/:projectId/role-grants', (ctx) => {
  const pid = Number(ctx.params.projectId)
  return db.roleGrants.filter((g) => g.project_id === pid)
})

register('POST', '/api/v1/projects/:projectId/role-grants', (ctx) => {
  const pid = Number(ctx.params.projectId)
  const body = ctx.body ?? {}
  if (!body.user_id || !body.role_slot) throw new MockError(400, 'E_VALID_GRANT', 'user_id 与 role_slot 必填')
  const user = db.users.find((u) => u.id === Number(body.user_id))
  const grant = {
    id: nextId('grant'),
    project_id: pid,
    user_id: Number(body.user_id),
    display_name: user?.display_name ?? `用户 ${body.user_id}`,
    role_slot: body.role_slot,
    granted_at: new Date().toISOString(),
  }
  db.roleGrants.push(grant)
  appendAudit({ event_type: 'project.grant_role', summary: `授予职责槽 ${grant.role_slot} → ${grant.display_name}`, project_id: pid, resource_type: 'project', resource_id: String(pid) })
  return { status: 201, data: grant }
})
