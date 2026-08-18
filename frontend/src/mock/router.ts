/**
 * Mock 路由器：`:param` 路径匹配、query 解析、JSON body、FormData 文件名/大小读取。
 */
export interface MockCtx {
  method: string
  path: string
  params: Record<string, string>
  query: URLSearchParams
  body: any
  /** multipart 上传时提取的文件信息 */
  file?: { name: string; size: number }
}

export interface MockResp {
  status: number
  data: unknown
}

export class MockError extends Error {
  status: number
  code: string
  details?: Record<string, unknown>

  constructor(status: number, code: string, message: string, details?: Record<string, unknown>) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

type Handler = (ctx: MockCtx) => MockResp | unknown

interface Route {
  method: string
  segments: string[]
  handler: Handler
}

const routes: Route[] = []

export function register(method: string, pattern: string, handler: Handler) {
  routes.push({
    method: method.toUpperCase(),
    segments: pattern.split('/').filter(Boolean),
    handler,
  })
}

function match(route: Route, path: string): Record<string, string> | null {
  const segs = path.split('/').filter(Boolean)
  if (segs.length !== route.segments.length) return null
  const params: Record<string, string> = {}
  for (let i = 0; i < segs.length; i++) {
    const p = route.segments[i]
    if (p.startsWith(':')) params[p.slice(1)] = decodeURIComponent(segs[i])
    else if (p !== segs[i]) return null
  }
  return params
}

export function dispatch(
  method: string,
  path: string,
  query: URLSearchParams,
  body: unknown,
  file?: MockCtx['file'],
): MockResp {
  const m = method.toUpperCase()
  for (const route of routes) {
    if (route.method !== m) continue
    const params = match(route, path)
    if (!params) continue
    const result = route.handler({ method: m, path, params, query, body, file })
    // handler 可直接返回数据（视为 200），或返回 {status, data}
    if (result && typeof result === 'object' && 'status' in (result as MockResp) && 'data' in (result as MockResp)) {
      return result as MockResp
    }
    return { status: 200, data: result }
  }
  throw new MockError(404, 'E_NOT_FOUND', `Mock 未注册路由：${m} ${path}`)
}

/* ---------- 分页工具 ---------- */

export function paginate<T>(items: T[], query: URLSearchParams) {
  const page = Math.max(1, Number(query.get('page') ?? 1) || 1)
  const pageSize = Math.min(100, Math.max(1, Number(query.get('page_size') ?? 20) || 20))
  const start = (page - 1) * pageSize
  return { items: items.slice(start, start + pageSize), total: items.length, page, page_size: pageSize }
}
