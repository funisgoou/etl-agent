import { MockError, paginate, register } from '../router'
import { appendAudit, db, nextId } from '../db'
import type { Connection } from '../../api/types'

const CONN_TYPES = new Set(['mysql', 'postgresql', 'oracle', 'doris', 'clickhouse', 's3', 'rest_api'])

/* ---------- 连接 ---------- */

register('GET', '/api/v1/projects/:projectId/connections', (ctx) => {
  const pid = Number(ctx.params.projectId)
  let list = db.connections.filter((c) => c.project_id === pid)
  const type = ctx.query.get('conn_type')
  if (type) list = list.filter((c) => c.conn_type === type)
  return paginate(list, ctx.query)
})

register('POST', '/api/v1/projects/:projectId/connections', (ctx) => {
  const body = ctx.body ?? {}
  if (!CONN_TYPES.has(body.conn_type)) {
    throw new MockError(400, 'E_VALID_CONN_TYPE', `未知连接类型：${body.conn_type}`)
  }
  const conn: Connection = {
    id: nextId('conn'),
    project_id: Number(ctx.params.projectId),
    name: String(body.name ?? 'unnamed'),
    conn_type: body.conn_type,
    status: 'unknown',
    config_json: { ...(body.config_json ?? {}), password: 'pa***rd' },
    created_at: new Date().toISOString(),
  }
  db.connections.push(conn)
  appendAudit({ event_type: 'connection.create', summary: `创建连接 ${conn.name}`, project_id: conn.project_id, resource_type: 'connection', resource_id: String(conn.id) })
  return { status: 201, data: conn }
})

register('PUT', '/api/v1/connections/:id', (ctx) => {
  const conn = db.connections.find((c) => c.id === Number(ctx.params.id))
  if (!conn) throw new MockError(404, 'E_NOT_FOUND', '连接不存在')
  const body = ctx.body ?? {}
  if (body.name) conn.name = String(body.name)
  if (body.config_json) conn.config_json = { ...conn.config_json, ...body.config_json, password: 'pa***rd' }
  conn.updated_at = new Date().toISOString()
  appendAudit({ event_type: 'config.change', summary: `编辑连接 ${conn.name}`, project_id: conn.project_id, resource_type: 'connection', resource_id: String(conn.id) })
  return conn
})

register('POST', '/api/v1/connections/:id/tests', (ctx) => {
  const conn = db.connections.find((c) => c.id === Number(ctx.params.id))
  if (!conn) throw new MockError(404, 'E_NOT_FOUND', '连接不存在')
  appendAudit({ event_type: 'connection.test', summary: `连通性测试 ${conn.name}`, project_id: conn.project_id, resource_type: 'connection', resource_id: String(conn.id) })
  if (conn.name === 'oracle_finance') {
    conn.status = 'unreachable'
    return { ok: false, message: '连接超时：10.0.6.8:1521 不可达（Oracle 监听未响应）' }
  }
  conn.status = 'connected'
  const versions: Record<string, string> = { mysql: '8.0.36', postgresql: '16.3', doris: '2.1.4', clickhouse: '24.3.2' }
  return { ok: true, latency_ms: 8 + Math.floor(Math.random() * 30), server_version: versions[conn.conn_type] ?? 'unknown' }
})

/* ---------- 探查 ---------- */

register('GET', '/api/v1/connections/:id/profiles', (ctx) => {
  const list = db.profiles.filter((p) => p.connection_id === Number(ctx.params.id))
  return paginate(list, ctx.query)
})

register('POST', '/api/v1/connections/:id/profiles', (ctx) => {
  const conn = db.connections.find((c) => c.id === Number(ctx.params.id))
  if (!conn) throw new MockError(404, 'E_NOT_FOUND', '连接不存在')
  const body = ctx.body ?? {}
  // orders 已有探查结果则直接复用演示数据
  if (conn.id === 1 && body.object_name === 'orders') {
    return { status: 201, data: db.profiles[0] }
  }
  const profile = {
    id: nextId('profile'),
    connection_id: conn.id,
    object_name: String(body.object_name ?? 'unknown'),
    schema_json: {
      primary_key: ['id'],
      columns: [
        { name: 'id', type: 'BIGINT', nullable: false, is_primary_key: true },
        { name: 'name', type: 'VARCHAR(64)', nullable: true },
        { name: 'created_at', type: 'DATETIME', nullable: false, is_incremental: true },
      ],
    },
    stats_json: { approx_rows: 10_000 },
    masked_sample_json: [{ id: 1, name: 's***e', created_at: '2026-06-10 08:00:00' }],
    created_at: new Date().toISOString(),
  }
  db.profiles.push(profile)
  appendAudit({ event_type: 'metadata.profile', summary: `元数据探查 ${conn.name}.${profile.object_name}`, project_id: conn.project_id, resource_type: 'connection', resource_id: String(conn.id) })
  return { status: 201, data: profile }
})

/* ---------- 文件资产 ---------- */

// ASSUMED: 接口文档只有上传，此处补列表供数据资产页
register('GET', '/api/v1/projects/:projectId/file-assets', (ctx) => {
  const pid = Number(ctx.params.projectId)
  const list = db.fileAssets.filter((f) => f.project_id === pid)
  return paginate(list, ctx.query)
})

register('POST', '/api/v1/file-assets', (ctx) => {
  const file = ctx.file
  if (!file) throw new MockError(400, 'E_VALID_FILE_FORMAT', '缺少上传文件')
  if (!file.name.toLowerCase().endsWith('.csv')) {
    throw new MockError(400, 'E_VALID_FILE_FORMAT', 'v1 仅支持 CSV 文件（D8）')
  }
  const id = nextId('file')
  const stem = file.name.replace(/\.csv$/i, '')
  const asset = {
    id,
    project_id: Number(ctx.body?.project_id ?? 1),
    file_name: file.name,
    file_path: `s3a://etl-assets/projects/${ctx.body?.project_id ?? 1}/file_assets/${id}/${file.name}`,
    file_size: file.size,
    file_format: 'csv' as const,
    schema_json: {
      columns: [
        { name: `${stem}_id`, inferred_type: 'long' },
        { name: 'name', inferred_type: 'string' },
        { name: 'email', inferred_type: 'string', sensitive: true, sample_masked: 'x***@example.com' },
        { name: 'created_at', inferred_type: 'datetime' },
      ],
    },
    created_at: new Date().toISOString(),
  }
  db.fileAssets.push(asset)
  appendAudit({ event_type: 'file.upload', summary: `上传文件资产 ${file.name}`, project_id: asset.project_id, resource_type: 'file_asset', resource_id: String(id) })
  return { status: 201, data: asset }
})

// ASSUMED: 原型资产页需要删除文件资产
register('DELETE', '/api/v1/file-assets/:id', (ctx) => {
  const idx = db.fileAssets.findIndex((f) => f.id === Number(ctx.params.id))
  if (idx < 0) throw new MockError(404, 'E_NOT_FOUND', '文件资产不存在')
  const [removed] = db.fileAssets.splice(idx, 1)
  appendAudit({ event_type: 'file.delete', summary: `删除文件资产 ${removed.file_name}`, project_id: removed.project_id, resource_type: 'file_asset', resource_id: String(removed.id) })
  return { status: 204, data: undefined }
})
