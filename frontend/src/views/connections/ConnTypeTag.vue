<template>
  <span class="conn-type-tag num" :style="style">
    <span class="conn-type-tag__dot" :style="{ background: color }" />
    {{ label }}
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

/** 连接类型彩色标签：MySQL 蓝 / PostgreSQL 青 / Oracle 红 / ClickHouse 黄 / Doris 紫 / 其余灰 */
const props = defineProps<{ type: string }>()

const MAP: Record<string, { label: string; color: string }> = {
  mysql: { label: 'MySQL', color: 'var(--blue)' },
  postgresql: { label: 'PostgreSQL', color: 'var(--cyan)' },
  oracle: { label: 'Oracle', color: 'var(--red)' },
  clickhouse: { label: 'ClickHouse', color: 'var(--amber)' },
  doris: { label: 'Doris', color: 'var(--violet)' },
  s3: { label: 'S3', color: 'var(--txt-2)' },
  rest_api: { label: 'REST API', color: 'var(--txt-2)' },
}

const meta = computed(() => MAP[props.type] ?? { label: props.type, color: 'var(--txt-2)' })
const label = computed(() => meta.value.label)
const color = computed(() => meta.value.color)

const style = computed(() => ({
  color: color.value,
  borderColor: `color-mix(in srgb, ${color.value} 38%, transparent)`,
  background: `color-mix(in srgb, ${color.value} 10%, transparent)`,
}))
</script>

<style scoped>
.conn-type-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border: 1px solid;
  border-radius: var(--r-sm);
  font-size: 12px;
  line-height: 20px;
  white-space: nowrap;
}
.conn-type-tag__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: none;
}
</style>
