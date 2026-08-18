<template>
  <div ref="el" class="v-chart" :style="{ height: typeof height === 'number' ? `${height}px` : height }" />
</template>

<script setup lang="ts">
/**
 * ECharts 统一封装：自动 init（主题 'obs'）/ resize / 销毁。
 * 用法：<VChart :option="option" :height="280" />
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { ECharts, EChartsOption } from 'echarts'
import { OBS_THEME, registerObsTheme } from './theme'

registerObsTheme()

const props = withDefaults(
  defineProps<{
    option: EChartsOption
    height?: number | string
  }>(),
  { height: 280 },
)

const el = ref<HTMLDivElement>()
let chart: ECharts | null = null
let ro: ResizeObserver | null = null

onMounted(() => {
  if (!el.value) return
  chart = echarts.init(el.value, OBS_THEME)
  chart.setOption(props.option)
  ro = new ResizeObserver(() => chart?.resize())
  ro.observe(el.value)
})

watch(
  () => props.option,
  (opt) => chart?.setOption(opt, { notMerge: true }),
  { deep: true },
)

onBeforeUnmount(() => {
  ro?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.v-chart { width: 100%; }
</style>
