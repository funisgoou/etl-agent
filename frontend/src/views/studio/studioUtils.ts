/**
 * Studio 页局部工具：版本标签 / 时间格式化（仅 src/views/studio 内使用）。
 */
import type { PipelineVersion } from '@/api'

/** 版本展示标签：优先 label，缺省回退 v{n}.0 */
export function versionLabel(v?: Pick<PipelineVersion, 'label' | 'version_number'> | null): string {
  if (!v) return '—'
  return v.label ?? `v${v.version_number}.0`
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

/** MM-DD HH:mm（操作历史 / 消息时间） */
export function fmtDateTime(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** YYYY-MM-DD（列表创建时间） */
export function fmtDate(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** HH:mm（聊天气泡时间） */
export function fmtTime(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 当前时刻 HH:mm */
export function nowTime(): string {
  return fmtTime(new Date().toISOString())
}
