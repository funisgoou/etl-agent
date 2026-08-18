import { get, post } from './client'
import type { BenchmarkRun } from './types'

export const benchApi = {
  /** 触发 Benchmark 评测（approver_security） */
  run(suiteVersion = 'v1.0') {
    return post<{ benchmark_run_id: number; status: string }>('/benchmarks/run', {
      suite_version: suiteVersion,
    })
  },
  get(id: number | string) {
    return get<BenchmarkRun>(`/benchmarks/runs/${id}`)
  },
  // ASSUMED: 接口文档只有单查，治理页趋势图需要历史列表
  list(params?: { project_id?: number | string; limit?: number }) {
    return get<BenchmarkRun[]>('/benchmarks/runs', params)
  },
}
