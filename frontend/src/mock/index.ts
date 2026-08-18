/**
 * Mock 安装入口。
 * - `import.meta.env.VITE_MOCK !== 'false'`（默认）启用：包装 window.fetch，凡 url 以
 *   `/api/` 或 `/health` 开头进入 mock 路由器，其余透传原生 fetch；同步替换
 *   window.EventSource 为 MockEventSource（仅拦截 /api/ 路径）。
 * - `createEventSource(url)` 是唯一合法的 EventSource 工厂：mock 模式返回
 *   MockEventSource，否则返回原生 EventSource。SSE 组合式函数必须走它。
 * - 所有 mock 响应带 120~400ms 随机延迟；数据全内存，刷新重置。
 */
import { dispatch, MockError } from './router'

// 注册全部路由（import 副作用）
import './handlers/auth'
import './handlers/projects'
import './handlers/connections'
import './handlers/pipelines'
import './handlers/preparations'
import './handlers/runs'
import './handlers/governance'
import './handlers/audit'

import { computeRun, db, isTerminal } from './db'

export const MOCK_ENABLED = import.meta.env.VITE_MOCK !== 'false'

const NativeFetch = window.fetch.bind(window)
const NativeEventSource = window.EventSource

function delay(): Promise<void> {
  return new Promise((r) => setTimeout(r, 120 + Math.random() * 280))
}

/* ---------- MockEventSource ---------- */

type Listener = (evt: MessageEvent) => void

/**
 * 按 run 进度时间线定时派发 status/metrics/supervision/done 事件（每 800ms 一拍），
 * 终态后自动 close。仅实现 useRunStream 依赖的接口子集。
 */
export class MockEventSource {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 2

  readonly CONNECTING = 0
  readonly OPEN = 1
  readonly CLOSED = 2

  readyState = 0
  onmessage: ((evt: MessageEvent) => void) | null = null
  onerror: ((evt: Event) => void) | null = null
  onopen: ((evt: Event) => void) | null = null

  private listeners = new Map<string, Set<Listener>>()
  private timer: ReturnType<typeof setInterval> | null = null
  private supervisionSent = false

  constructor(public readonly url: string) {
    const m = /\/execution-runs\/(\d+)\/stream/.exec(url)
    const runId = m ? Number(m[1]) : NaN

    queueMicrotask(() => {
      this.readyState = 1
      this.onopen?.(new Event('open'))
      if (!Number.isFinite(runId) || !db.runs.some((r) => r.id === runId)) {
        this.emit('error', new Event('error'))
        this.onerror?.(new Event('error'))
        this.close()
        return
      }
      this.tick(runId)
      this.timer = setInterval(() => this.tick(runId), 800)
    })
  }

  addEventListener(type: string, listener: Listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set())
    this.listeners.get(type)!.add(listener)
  }

  removeEventListener(type: string, listener: Listener) {
    this.listeners.get(type)?.delete(listener)
  }

  close() {
    if (this.timer) clearInterval(this.timer)
    this.timer = null
    this.readyState = 2
    this.listeners.clear()
  }

  private emit(type: string, evt: MessageEvent | Event) {
    const set = this.listeners.get(type)
    if (set) for (const fn of [...set]) fn(evt as MessageEvent)
  }

  private emitData(type: string, data: unknown) {
    this.emit(type, new MessageEvent(type, { data: JSON.stringify(data) }))
  }

  private tick(runId: number) {
    if (this.readyState !== 1) return
    const run = computeRun(runId)
    if (!run) {
      this.close()
      return
    }

    // status 事件
    this.emitData('status', {
      status: run.status,
      sub_stage: run.sub_stage ?? undefined,
      input_records: run.input_records,
      output_records: run.output_records,
      error_records: run.error_records,
    })

    // metrics 事件
    if (run.status === 'running') {
      const elapsed = run.started_at ? (Date.now() - new Date(run.started_at).getTime()) / 1000 : 1
      this.emitData('metrics', {
        input_records: run.input_records,
        output_records: run.output_records,
        error_records: run.error_records,
        bytes_processed: run.bytes_processed,
        throughput_rps: Math.max(1, Math.floor(run.input_records / Math.max(1, elapsed))),
      })

      // supervision：中途发一次 warning（error_reject_rate 0.07 / 阈值 0.1）
      if (!this.supervisionSent && run.sub_stage === 'SPLITTING') {
        this.supervisionSent = true
        this.emitData('supervision', {
          decision: 'warning',
          metric: 'error_reject_rate',
          value: 0.07,
          threshold: 0.1,
        })
      }
    }

    // done：终态后服务端关闭流
    if (isTerminal(run.status)) {
      this.emitData('done', {
        status: run.status,
        row_count_check: run.quality_report?.row_count_check ?? 'passed',
      })
      this.close()
    }
  }
}

/* ---------- fetch 包装 ---------- */

function isMockUrl(pathname: string): boolean {
  return pathname.startsWith('/api/') || pathname === '/health'
}

async function mockFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = new URL(
    typeof input === 'string' ? input : input instanceof URL ? input.href : input.url,
    window.location.origin,
  )
  if (!isMockUrl(url.pathname)) {
    return NativeFetch(input as RequestInfo, init)
  }

  await delay()

  let body: unknown
  let file: { name: string; size: number } | undefined
  const raw = init?.body
  if (typeof raw === 'string') {
    try {
      body = JSON.parse(raw)
    } catch {
      body = raw
    }
  } else if (raw instanceof FormData) {
    body = {}
    raw.forEach((v, k) => {
      if (v instanceof File) file = { name: v.name, size: v.size }
      else (body as Record<string, string>)[k] = String(v)
    })
  }

  try {
    const resp = dispatch(init?.method ?? 'GET', url.pathname, url.searchParams, body, file)
    if (resp.status === 204) {
      return new Response(null, { status: 204 })
    }
    return new Response(JSON.stringify(resp.data), {
      status: resp.status,
      headers: { 'Content-Type': 'application/json' },
    })
  } catch (err) {
    if (err instanceof MockError) {
      return new Response(
        JSON.stringify({
          code: err.code,
          message: err.message,
          details: err.details,
          trace_id: `01JMOCK${Date.now().toString(36).toUpperCase()}`,
        }),
        { status: err.status, headers: { 'Content-Type': 'application/json' } },
      )
    }
    return new Response(
      JSON.stringify({ code: 'E_INTERNAL', message: String(err), trace_id: '01JMOCKINTERNAL' }),
      { status: 500, headers: { 'Content-Type': 'application/json' } },
    )
  }
}

/** 非 /api/ 路径的 EventSource 透传原生实现 */
class RoutedEventSource {
  constructor(url: string | URL, config?: EventSourceInit) {
    const u = String(url)
    if (MOCK_ENABLED && u.includes('/api/')) {
      return new MockEventSource(u) as unknown as EventSource
    }
    return new NativeEventSource(u, config) as EventSource
  }
}

/** 在 main.ts 最前调用；VITE_MOCK=false 时为 no-op */
export function installMock() {
  if (!MOCK_ENABLED) return
  window.fetch = mockFetch as typeof window.fetch
  window.EventSource = RoutedEventSource as unknown as typeof EventSource
}

/**
 * EventSource 可注入工厂 —— SSE 代码必须经此创建，
 * mock 模式返回 MockEventSource，否则原生 EventSource。
 */
export function createEventSource(url: string): EventSource {
  if (MOCK_ENABLED) return new MockEventSource(url) as unknown as EventSource
  return new NativeEventSource(url)
}
