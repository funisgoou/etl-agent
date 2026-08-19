<template>
  <section class="glass-panel" :class="{ 'hover-lift': hoverable, 'is-strong': strong }">
    <header v-if="title || $slots.actions" class="glass-panel__head">
      <div class="glass-panel__title-wrap">
        <span class="glass-panel__bar" />
        <h3 class="glass-panel__title">{{ title }}</h3>
        <span v-if="subtitle" class="glass-panel__sub">{{ subtitle }}</span>
      </div>
      <div class="glass-panel__actions"><slot name="actions" /></div>
    </header>
    <div class="glass-panel__body" :style="{ padding: bodyPadding }">
      <slot />
    </div>
  </section>
</template>

<script setup lang="ts">
/** 玻璃拟态面板：全项目内容容器标准 */
withDefaults(
  defineProps<{
    title?: string
    subtitle?: string
    /** hover 上移 + 发光 */
    hoverable?: boolean
    /** 更强不透明度（弹层内嵌场景） */
    strong?: boolean
    bodyPadding?: string
  }>(),
  { title: '', subtitle: '', hoverable: false, strong: false, bodyPadding: '20px' },
)
</script>

<style scoped>
.glass-panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  overflow: hidden;
}
.glass-panel.is-strong { background: var(--panel-strong); }

.glass-panel__body { flex: 1; min-height: 0; display: flex; flex-direction: column; }

.glass-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--line);
}

.glass-panel__title-wrap { display: flex; align-items: baseline; gap: 10px; min-width: 0; }

.glass-panel__bar {
  width: 3px;
  height: 14px;
  border-radius: 2px;
  background: var(--grad);
  align-self: center;
  flex: none;
}

.glass-panel__title { font-size: 15px; color: var(--txt-0); white-space: nowrap; }
.glass-panel__sub { font-size: 12px; color: var(--txt-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.glass-panel__actions { display: flex; align-items: center; gap: 8px; flex: none; }
</style>
