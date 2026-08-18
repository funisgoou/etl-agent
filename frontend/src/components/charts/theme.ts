/**
 * ECharts 全局主题 'obs'（深空底 + 品牌色板 + 细网格线）。
 * 在任何 echarts.init 之前 import 本模块即完成注册（VChart.vue 已内置）。
 */
import * as echarts from 'echarts'

export const OBS_THEME = 'obs'

let registered = false

export function registerObsTheme() {
  if (registered) return
  registered = true
  echarts.registerTheme(OBS_THEME, {
    backgroundColor: 'transparent',
    color: ['#22d3ee', '#818cf8', '#c084fc', '#34d399', '#fbbf24', '#fb7185', '#60a5fa'],
    textStyle: { color: '#94a3b8', fontFamily: 'Sora, PingFang SC, Microsoft YaHei, sans-serif' },
    title: { textStyle: { color: '#e6edf7' }, subtextStyle: { color: '#5b6b83' } },
    categoryAxis: {
      axisLine: { lineStyle: { color: 'rgba(148,163,184,.28)' } },
      axisTick: { show: false },
      axisLabel: { color: '#5b6b83' },
      splitLine: { lineStyle: { color: 'rgba(148,163,184,.08)' } },
    },
    valueAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#5b6b83' },
      splitLine: { lineStyle: { color: 'rgba(148,163,184,.08)' } },
    },
    logAxis: {
      axisLabel: { color: '#5b6b83' },
      splitLine: { lineStyle: { color: 'rgba(148,163,184,.08)' } },
    },
    timeAxis: {
      axisLabel: { color: '#5b6b83' },
      splitLine: { lineStyle: { color: 'rgba(148,163,184,.08)' } },
    },
    legend: { textStyle: { color: '#94a3b8' } },
    tooltip: {
      backgroundColor: 'rgba(15,23,42,.92)',
      borderColor: 'rgba(148,163,184,.28)',
      textStyle: { color: '#e6edf7' },
    },
  })
}
