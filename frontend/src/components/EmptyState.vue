<template>
  <div class="empty-state">
    <div class="empty-state__orbit">
      <span class="empty-state__core" />
    </div>
    <p class="empty-state__title">{{ title }}</p>
    <p v-if="description" class="empty-state__desc">{{ description }}</p>
    <div v-if="$slots.default" class="empty-state__actions"><slot /></div>
  </div>
</template>

<script setup lang="ts">
/** 空状态 */
withDefaults(defineProps<{ title?: string; description?: string }>(), {
  title: '暂无数据',
  description: '',
})
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;
}
.empty-state__orbit {
  width: 64px;
  height: 64px;
  border: 1px dashed var(--line-strong);
  border-radius: 50%;
  display: grid;
  place-items: center;
  animation: spin 14s linear infinite;
  margin-bottom: 16px;
}
.empty-state__core {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--grad);
  opacity: 0.85;
  box-shadow: var(--glow);
}
.empty-state__title { margin: 0; font-size: 15px; color: var(--txt-0); }
.empty-state__desc { margin: 6px 0 0; font-size: 13px; color: var(--txt-2); max-width: 380px; }
.empty-state__actions { margin-top: 16px; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
