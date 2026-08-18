/**
 * API 客户端：fetch 封装。
 * - baseURL `/api/v1`；自动携带 `Authorization: Bearer <token>`（localStorage 'etl_token'）
 * - 错误信封 {code,message,details,trace_id} → ApiError
 * - 401 → 清 token 并跳转 /login
 */

export const TOKEN_KEY = 'etl_token'
const BASE_URL = '/api/v1'

export class ApiError extends Error {
  code: string
  details?: Record<string, unknown>
  traceId?: string
  status: number

  constructor(
    status: number,
    code: string,
    message: string,
    details?: Record<string, unknown>,
    traceId?: string,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
    this.traceId = traceId
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

function handleUnauthorized() {
  clearToken()
  localStorage.removeItem('etl_user')
  if (window.location.pathname !== '/login') {
    window.location.href = '/login'
  }
}

/** 查询参数对象（任意可枚举对象，值为标量） */
type Query = object

function buildUrl(path: string, params?: Query): string {
  const url = path.startsWith('http') || path === '/health' ? path : `${BASE_URL}${path}`
  if (!params) return url
  const qs = Object.entries(params as Record<string, unknown>)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&')
  return qs ? `${url}${url.includes('?') ? '&' : '?'}${qs}` : url
}

async function parseError(resp: Response): Promise<ApiError> {
  let code = 'E_INTERNAL'
  let message = `请求失败（HTTP ${resp.status}）`
  let details: Record<string, unknown> | undefined
  let traceId: string | undefined
  try {
    const body = await resp.json()
    if (body && typeof body === 'object') {
      code = body.code ?? code
      message = body.message ?? message
      details = body.details
      traceId = body.trace_id
    }
  } catch {
    /* 非 JSON 错误体，保留默认信息 */
  }
  return new ApiError(resp.status, code, message, details, traceId)
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  params?: Query,
): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const init: RequestInit = { method, headers }
  if (body !== undefined && body !== null) {
    headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }

  const resp = await fetch(buildUrl(path, params), init)
  if (resp.status === 401) {
    handleUnauthorized()
    throw await parseError(resp)
  }
  if (resp.status === 204) return undefined as T
  if (!resp.ok) throw await parseError(resp)
  return (await resp.json()) as T
}

export function get<T>(path: string, params?: Query): Promise<T> {
  return request<T>('GET', path, undefined, params)
}

export function post<T>(path: string, body?: unknown, params?: Query): Promise<T> {
  return request<T>('POST', path, body, params)
}

export function put<T>(path: string, body?: unknown, params?: Query): Promise<T> {
  return request<T>('PUT', path, body, params)
}

export function del<T>(path: string, params?: Query): Promise<T> {
  return request<T>('DELETE', path, undefined, params)
}

/** multipart 上传（不设置 Content-Type，交给浏览器生成 boundary） */
export async function upload<T>(path: string, formData: FormData): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const resp = await fetch(buildUrl(path), { method: 'POST', headers, body: formData })
  if (resp.status === 401) {
    handleUnauthorized()
    throw await parseError(resp)
  }
  if (!resp.ok) throw await parseError(resp)
  return (await resp.json()) as T
}
