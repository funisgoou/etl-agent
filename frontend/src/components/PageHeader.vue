<template>
  <div class="page-header rise-in">
    <div class="page-header__text">
      <h2 class="page-header__title">{{ title }}</h2>
      <p v-if="subtitle" class="page-header__sub">{{ subtitle }}</p>
    </div>
    <div class="page-header__actions"><slot name="actions" /></div>
  </div>
</template>

<script setup lang="ts">
/** 页头：标题 / 副标题 / actions 插槽 */
defineProps<{ title: string; subtitle?: string }>()
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}
.page-header__title {
  font-size: 24px;
  letter-spacing: 0.02em;
  background: linear-gradient(120deg, var(--txt-0) 30%, var(--cyan) 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.page-header__sub { margin: 4px 0 0; font-size: 13px; color: var(--txt-1); }
.page-header__actions { display: flex; align-items: center; gap: 10px; flex: none; }
</style>
