<template>
  <div class="code-block">
    <div class="code-block__bar">
      <span class="code-block__lang">{{ lang.toUpperCase() }}</span>
      <button class="code-block__copy" type="button" @click="copy">
        {{ copied ? '已复制' : '复制' }}
      </button>
    </div>
    <pre class="code-block__pre"><code><span
      v-for="(line, i) in lines"
      :key="i"
      class="code-block__line"
    ><span class="code-block__ln">{{ i + 1 }}</span><span class="code-block__lc" v-html="highlight(line)" /></span></code></pre>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

/** 代码块：mono、行号、复制按钮、关键词级简单高亮（hocon / sql） */
const props = withDefaults(
  defineProps<{
    code: string
    lang?: 'hocon' | 'sql' | 'json' | 'text'
  }>(),
  { lang: 'text' },
)

const copied = ref(false)
const lines = computed(() => props.code.replace(/\n$/, '').split('\n'))

const KEYWORDS: Record<string, RegExp> = {
  hocon: /\b(env|source|transform|sink|Jdbc|Doris|Sql|ClickHouse|S3|plugin_output|plugin_input|query|url|table|fenodes|parallelism|job\.mode)\b/g,
  sql: /\b(SELECT|FROM|WHERE|AND|OR|NOT|NULL|IS|INSERT|INTO|VALUES|UPDATE|DELETE|JOIN|LEFT|RIGHT|INNER|GROUP|BY|ORDER|LIMIT|AS|DISTINCT|CASE|WHEN|THEN|END)\b/gi,
  json: /("(?:\\.|[^"\\])*")\s*:/g,
  text: /$^/g,
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function highlight(line: string): string {
  let out = escapeHtml(line)
  // 字符串
  out = out.replace(/(&quot;.*?&quot;|".*?"|'.*?')/g, '<span class="tk-str">$1</span>')
  // 注释
  out = out.replace(/(#.*$|--.*$)/, '<span class="tk-cmt">$1</span>')
  // 关键词
  const kw = KEYWORDS[props.lang] ?? KEYWORDS.text
  out = out.replace(kw, '<span class="tk-kw">$1</span>')
  // 数字
  out = out.replace(/\b(\d[\d,._]*)\b/g, '<span class="tk-num">$1</span>')
  return out
}

async function copy() {
  try {
    await navigator.clipboard.writeText(props.code)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    /* 剪贴板不可用时静默 */
  }
}
</script>

<style scoped>
.code-block {
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: rgba(3, 7, 15, 0.72);
  overflow: hidden;
}
.code-block__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  border-bottom: 1px solid var(--line);
  background: rgba(148, 163, 184, 0.05);
}
.code-block__lang { font-size: 11px; color: var(--txt-2); font-family: var(--font-num); letter-spacing: 0.08em; }
.code-block__copy {
  border: none;
  background: transparent;
  color: var(--cyan);
  font-size: 12px;
  cursor: pointer;
  font-family: var(--font-ui);
}
.code-block__copy:hover { text-shadow: 0 0 12px rgba(34, 211, 238, 0.6); }
.code-block__pre {
  margin: 0;
  padding: 12px 0;
  overflow: auto;
  font-family: var(--font-num);
  font-size: 12.5px;
  line-height: 1.7;
}
.code-block__line { display: flex; white-space: pre; }
.code-block__ln {
  flex: none;
  width: 44px;
  text-align: right;
  padding-right: 14px;
  color: var(--txt-2);
  opacity: 0.55;
  user-select: none;
}
.code-block__lc { color: var(--txt-0); }
:deep(.tk-kw) { color: var(--cyan); }
:deep(.tk-str) { color: var(--green); }
:deep(.tk-num) { color: var(--violet); }
:deep(.tk-cmt) { color: var(--txt-2); font-style: italic; }
</style>
