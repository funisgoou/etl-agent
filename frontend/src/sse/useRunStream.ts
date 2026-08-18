/**
 * SSE 运行流组合式函数（D7）。
 * EventSource 一律经 mock/index.ts 的可注入工厂创建（mock 模式自动替换为 MockEventSource）。
 * done 或出错自动关闭；组件卸载自动关闭。
 */
import { onBeforeUnmount, reactive, ref, watch, type Ref } from 'vue'
import { createEventSource } from '@/mock'
import type { RunStatus, SubStage } from '@/api'

export interface SupervisionEvent {
  decision: 'ok' | 'warning' | 'breach'
  metric: string
  value: number
  threshold: number
  at: string
}

export interface RunStreamState {
  connected: boolean
  status: RunStatus | null
  sub_stage: SubStage | null
  input_records: number
  output_records: number
  error_records: number
  bytes_processed: number
  throughput_rps: number | null
  supervision: SupervisionEvent[]
  /** done 事件载荷；终态后非空 */
  done: { status: RunStatus; row_count_check?: string } | null
  error: string | null
}

function parse<T>(evt: MessageEvent): T | null {
  try {
    return JSON.parse(evt.data) as T
  } catch {
    return null
  }
}

export function useRunStream(runId: Ref<number | string | null>) {
  const state = reactive<RunStreamState>({
    connected: false,
    status: null,
    sub_stage: null,
    input_records: 0,
    output_records: 0,
    error_records: 0,
    bytes_processed: 0,
    throughput_rps: null,
    supervision: [],
    done: null,
    error: null,
  })

  let es: EventSource | null = null

  function close() {
    es?.close()
    es = null
    state.connected = false
  }

  function open(id: number | string) {
    close()
    state.done = null
    state.error = null
    es = createEventSource(`/api/v1/execution-runs/${id}/stream`)

    es.addEventListener('status', (evt) => {
      const d = parse<{ status: RunStatus; sub_stage?: SubStage; input_records?: number; output_records?: number; error_records?: number }>(evt as MessageEvent)
      if (!d) return
      state.connected = true
      state.status = d.status
      state.sub_stage = d.sub_stage ?? null
      if (d.input_records !== undefined) state.input_records = d.input_records
      if (d.output_records !== undefined) state.output_records = d.output_records
      if (d.error_records !== undefined) state.error_records = d.error_records
    })

    es.addEventListener('metrics', (evt) => {
      const d = parse<{ input_records: number; output_records: number; error_records: number; bytes_processed: number; throughput_rps: number }>(evt as MessageEvent)
      if (!d) return
      state.input_records = d.input_records
      state.output_records = d.output_records
      state.error_records = d.error_records
      state.bytes_processed = d.bytes_processed
      state.throughput_rps = d.throughput_rps
    })

    es.addEventListener('supervision', (evt) => {
      const d = parse<Omit<SupervisionEvent, 'at'>>(evt as MessageEvent)
      if (!d) return
      state.supervision.push({ ...d, at: new Date().toISOString() })
    })

    es.addEventListener('done', (evt) => {
      const d = parse<{ status: RunStatus; row_count_check?: string }>(evt as MessageEvent)
      state.done = d ?? { status: 'succeeded' }
      if (d) state.status = d.status
      close() // 终态自动关闭
    })

    es.addEventListener('error', () => {
      state.error = 'SSE 连接中断'
      close() // 报错自动关闭
    })
  }

  watch(
    runId,
    (id) => {
      if (id === null || id === undefined) close()
      else open(id)
    },
    { immediate: true },
  )

  onBeforeUnmount(close)

  return { state, close, reopen: () => runId.value != null && open(runId.value) }
}
