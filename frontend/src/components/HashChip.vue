<template>
  <button class="hash-chip num" type="button" :title="`点击复制：${hash}`" @click="copy">
    <span class="hash-chip__text">{{ short }}</span>
    <el-icon :size="12" class="hash-chip__icon"><CopyDocument /></el-icon>
  </button>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { CopyDocument } from '@element-plus/icons-vue'

/** 哈希片段：截断展示 + 点击复制（artifact_digest / event_hash / fingerprint 通用） */
const props = withDefaults(
  defineProps<{
    hash: string
    /** 前段保留字符数 */
    head?: number
    /** 尾段保留字符数（0 则不显示尾段） */
    tail?: number
  }>(),
  { head: 6, tail: 4 },
)

const copied = ref(false)

const short = computed(() => {
  const h = props.hash
  if (!h) return '-'
  if (h.length <= props.head + props.tail + 1) return h
  const tail = props.tail > 0 ? `…${h.slice(-props.tail)}` : '…'
  return copied.value ? '已复制' : `${h.slice(0, props.head)}${tail}`
})

async function copy() {
  try {
    await navigator.clipboard.writeText(props.hash)
    copied.value = true
    setTimeout(() => (copied.value = false), 1200)
  } catch {
    /* 剪贴板不可用时静默 */
  }
}
</script>

<style scoped>
.hash-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: rgba(148, 163, 184, 0.07);
  color: var(--txt-1);
  font-size: 12px;
  cursor: pointer;
  transition: color 0.2s, border-color 0.2s, box-shadow 0.2s;
}
.hash-chip:hover {
  color: var(--cyan);
  border-color: rgba(34, 211, 238, 0.4);
  box-shadow: 0 0 12px rgba(34, 211, 238, 0.15);
}
.hash-chip__icon { opacity: 0.7; }
</style>
