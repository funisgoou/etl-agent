<template>
  <span class="risk-tag" :style="style">{{ level }}</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { RiskLevel } from '@/api'

/** 风险等级标签：P0 红 / P1 橙 / P2 蓝 / P3 灰 */
const props = defineProps<{ level: RiskLevel | string }>()

const COLORS: Record<string, string> = {
  P0: 'var(--red)',
  P1: 'var(--amber)',
  P2: 'var(--blue)',
  P3: 'var(--txt-2)',
}

const style = computed(() => {
  const c = COLORS[props.level] ?? 'var(--txt-1)'
  return {
    color: c,
    borderColor: `color-mix(in srgb, ${c} 45%, transparent)`,
    background: `color-mix(in srgb, ${c} 12%, transparent)`,
  }
})
</script>

<style scoped>
.risk-tag {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border: 1px solid;
  border-radius: var(--r-sm);
  font-size: 12px;
  font-weight: 700;
  font-family: var(--font-num);
  line-height: 20px;
}
</style>
