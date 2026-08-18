<template>
  <span class="status-pill" :style="style">
    <span class="dot" :class="{ 'is-live': live }" />
    <span class="status-pill__text">{{ text }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

/**
 * 状态徽标：run / connection / preparation / version / 通用域的 status → 颜色语义，
 * 此处单点定义，全项目复用，不要在页面里另起映射。
 */
const props = withDefaults(
  defineProps<{
    status: string
    /** 覆盖默认文案 */
    text?: string
  }>(),
  { text: undefined },
)

interface Meta { color: string; label: string; live?: boolean }

const MAP: Record<string, Meta> = {
  // 执行运行
  pending: { color: 'var(--txt-2)', label: '排队中' },
  running: { color: 'var(--cyan)', label: '运行中', live: true },
  succeeded: { color: 'var(--green)', label: '成功' },
  failed: { color: 'var(--red)', label: '失败' },
  cancelled: { color: 'var(--txt-2)', label: '已取消' },
  rolled_back: { color: 'var(--amber)', label: '已回滚' },
  // 连接
  connected: { color: 'var(--green)', label: '已连接' },
  unreachable: { color: 'var(--red)', label: '不可达' },
  unknown: { color: 'var(--txt-2)', label: '未测试' },
  // 准备单
  approved: { color: 'var(--green)', label: '审批通过' },
  rejected: { color: 'var(--red)', label: '已拒绝' },
  committed: { color: 'var(--blue)', label: '已提交执行' },
  expired: { color: 'var(--txt-2)', label: '已过期' },
  // 版本状态机（D17）
  draft: { color: 'var(--txt-2)', label: '草稿' },
  generating: { color: 'var(--violet)', label: '生成中', live: true },
  gated: { color: 'var(--blue)', label: '门禁通过' },
  frozen: { color: 'var(--cyan)', label: '已冻结' },
  executing: { color: 'var(--cyan)', label: '执行中', live: true },
  executed: { color: 'var(--green)', label: '已执行' },
  retired: { color: 'var(--txt-2)', label: '已退役' },
  // 审批请求
  decided: { color: 'var(--green)', label: '已决策' },
  // 进化候选
  proposed: { color: 'var(--amber)', label: '待评审' },
  // 通用
  ok: { color: 'var(--green)', label: '正常' },
  degraded: { color: 'var(--amber)', label: '降级' },
  waiting_input: { color: 'var(--amber)', label: '等待输入', live: true },
}

const meta = computed<Meta>(() => MAP[props.status] ?? { color: 'var(--txt-1)', label: props.status })
const text = computed(() => props.text ?? meta.value.label)
const live = computed(() => meta.value.live === true)

const style = computed(() => ({
  color: meta.value.color,
  borderColor: `color-mix(in srgb, ${meta.value.color} 38%, transparent)`,
  background: `color-mix(in srgb, ${meta.value.color} 10%, transparent)`,
}))
</script>

<style scoped>
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border: 1px solid;
  border-radius: 999px;
  font-size: 12px;
  line-height: 20px;
  white-space: nowrap;
  font-family: var(--font-num);
}
.status-pill__text { font-family: var(--font-ui); }
</style>
