import { register } from '../router'
import { currentUser } from '../data'
import { db } from '../db'

/** 认证：任意账号密码登录成功，固定返回张伟（角色/职责槽全集） */
register('POST', '/api/v1/auth/login', () => {
  return {
    status: 200,
    data: {
      token: `mock-token-${Date.now().toString(36)}`,
      expires_at: new Date(Date.now() + 12 * 3600_000).toISOString(),
      user: currentUser,
    },
  }
})

register('POST', '/api/v1/auth/register', (ctx) => {
  const body = ctx.body ?? {}
  const user = {
    id: db.users.length + 10,
    username: body.username ?? 'new_user',
    display_name: body.display_name ?? body.username ?? '新用户',
    email: body.email ?? '',
    status: 'active' as const,
    roles: ['engineer' as const],
    role_slots: [],
  }
  return { status: 201, data: user }
})

register('POST', '/api/v1/auth/logout', () => {
  return { status: 204, data: undefined }
})

register('GET', '/health', () => {
  return {
    status: 200,
    data: {
      status: 'ok',
      components: {
        postgres: 'ok',
        redis: 'ok',
        doris: 'ok',
        seatunnel: 'ok',
        minio: 'ok',
        vault: 'ok',
        mysql: 'ok',
      },
    },
  }
})
