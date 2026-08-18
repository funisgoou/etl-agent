import { get, post } from './client'
import type { AgentRun, DesignResult } from './types'

export const genApi = {
  /** 触发 LangGraph 候选生成（202） */
  trigger(versionId: number | string, prompt: string) {
    return post<{ run_id: number; thread_id: string; status: string }>(
      `/versions/${versionId}/generation`,
      { prompt },
    )
  },
  /** 轮询 agent-run 状态机 */
  getRun(runId: number | string) {
    return get<AgentRun>(`/agent-runs/${runId}`)
  },
  /** 提交澄清回答（从 checkpoint 恢复，D10） */
  answer(runId: number | string, answer: Record<string, string>) {
    return post<{ run_id: number; status: string }>(`/agent-runs/${runId}/answers`, { answer })
  },
  /** 设计结果（方案审查视图数据源） */
  getDesign(versionId: number | string) {
    return get<DesignResult>(`/versions/${versionId}/design`)
  },
  /** 冻结不可变版本 */
  freeze(versionId: number | string) {
    return post<{ version_id: number; artifact_digest: string; is_immutable: boolean }>(
      `/versions/${versionId}/freeze`,
    )
  },
  /** 受管试运行（免四眼，进账本） */
  dryRun(versionId: number | string) {
    return post<{ execution_run_id: number; audit_event_id: number; status: string }>(
      `/versions/${versionId}/dry-run`,
    )
  },
}
