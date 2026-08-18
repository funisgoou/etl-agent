<template>
  <div class="stat-card hover-lift">
    <div class="stat-card__top">
      <span class="stat-card__label">{{ label }}</span>
      <span v-if="icon" class="stat-card__icon" :style="{ color: accent }">
        <el-icon :size="16"><component :is="icon" /></el-icon>
      </span>
    </div>
    <div class="stat-card__value num" :style="{ color: accent }">{{ display }}</div>
    <div class="stat-card__foot">
      <span v-if="delta !== undefined" class="stat-card__delta" :class="deltaClass">
        {{ deltaText }}
      </span>
      <span v-if="hint" class="stat-card__hint">{{ hint }}</span>
    </div>
    <div v-if="trend && trend.length > 1" class="stat-card__spark">
      <svg viewBox="0 0 100 28" preserveAspectRatio="none">
        <polyline :points="sparkPoints" fill="none" :stroke="accent" stroke-width="1.6" stroke-linecap="round" />
      </svg>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

/** 指标卡：label、大数字（mono）、delta 涨跌、icon、迷你趋势线 */
const props = withDefaults(
  defineProps<{
    label: string
    value: number | string
    /** 涨跌百分比，正涨负跌 */
    delta?: number
    hint?: string
    icon?: object
    accent?: string
    /** 迷你趋势数据点 */
    trend?: number[]
    /** 数字格式化（默认千分位） */
    format?: (v: number | string) => string
  }>(),
  { delta: undefined, hint: '', icon: undefined, accent: 'var(--txt-0)', trend: undefined, format: undefined },
)

const display = computed(() => {
  if (props.format) return props.format(props.value)
  if (typeof props.value === 'number') return props.value.toLocaleString('en-US')
  return props.value
})

const deltaClass = computed(() => (props.delta === undefined ? '' : props.delta >= 0 ? 'is-up' : 'is-down'))
const deltaText = computed(() => {
  if (props.delta === undefined) return ''
  const sign = props.delta >= 0 ? '▲' : '▼'
  return `${sign} ${Math.abs(props.delta).toFixed(1)}%`
})

const sparkPoints = computed(() => {
  const t = props.trend ?? []
  if (t.length < 2) return ''
  const min = Math.min(...t)
  const max = Math.max(...t)
  const span = max - min || 1
  return t
    .map((v, i) => `${(i / (t.length - 1)) * 100},${26 - ((v - min) / span) * 24}`)
    .join(' ')
})
</script>

<style scoped>
.stat-card {
  position: relative;
  padding: 16px 18px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  backdrop-filter: blur(14px);
  overflow: hidden;
}
.stat-card__top { display: flex; align-items: center; justify-content: space-between; }
.stat-card__label { font-size: 12px; color: var(--txt-1); letter-spacing: 0.04em; }
.stat-card__icon { opacity: 0.9; }
.stat-card__value {
  margin-top: 6px;
  font-size: 30px;
  font-weight: 600;
  line-height: 1.2;
  letter-spacing: -0.02em;
}
.stat-card__foot { display: flex; align-items: center; gap: 8px; margin-top: 6px; min-height: 18px; }
.stat-card__delta { font-size: 12px; font-family: var(--font-num); }
.stat-card__delta.is-up { color: var(--green); }
.stat-card__delta.is-down { color: var(--red); }
.stat-card__hint { font-size: 12px; color: var(--txt-2); }
.stat-card__spark { margin-top: 8px; height: 28px; opacity: 0.85; }
.stat-card__spark svg { width: 100%; height: 100%; }
</style>
