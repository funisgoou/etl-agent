<template>
  <div class="gov">
    <PageHeader title="安全治理与 Benchmark" subtitle="自动化评测大盘 + Prompt/策略改进的全生命周期管理（灰度→评测→准入）">
      <template #actions>
        <el-button type="primary" :icon="VideoPlay" :loading="benchRunning" @click="runBenchmark">
          {{ benchRunning ? '评测中…' : '触发 Benchmark 评测' }}
        </el-button>
      </template>
    </PageHeader>

    <!-- 指标带 -->
    <div class="gov__stats rise-in">
      <StatCard label="编译通过率" :value="pct(metrics?.compile_pass_rate)" hint="较上版本 ↑ 2.1%" :icon="Document" accent="var(--cyan)" />
      <StatCard label="字段 F1" :value="metrics?.field_f1?.toFixed(2) ?? '—'" hint="较上版本 ↑ 0.03" :icon="Aim" accent="var(--violet)" />
      <StatCard label="空跑成功率" :value="pct(metrics?.dry_run_pass_rate)" hint="较上版本 ↓ 1.2%" :icon="VideoPlay" accent="var(--blue)" />
      <StatCard label="安全拦截率" :value="pct(metrics?.block_rate)" hint="持平 vs 上版本" :icon="Lock" accent="var(--green)" />
      <StatCard label="误伤率" :value="pct(metrics?.false_positive_rate)" hint="较上版本 ↓ 0.8%" :icon="WarnTriangleFilled" accent="var(--amber)" />
    </div>

    <div class="gov__grid">
      <!-- 综合健康度 -->
      <GlassPanel class="rise-in" title="综合健康度" :subtitle="`高于准入阈值 ${THRESHOLD}`">
        <VChart :option="gaugeOption" :height="220" />
        <p class="gov__health-status" :class="healthy ? 'is-ok' : 'is-bad'">
          状态：{{ healthy ? '达标' : '未达标' }}
          <span class="gov__health-note">阈值线 ≥{{ THRESHOLD }} · 低于阈值阻断发布</span>
        </p>
      </GlassPanel>

      <!-- Benchmark 趋势 -->
      <GlassPanel class="rise-in" title="最近 10 次 Benchmark 运行" :subtitle="`阈值 ${THRESHOLD} 分`">
        <VChart :option="trendOption" :height="270" />
      </GlassPanel>
    </div>

    <!-- 改进管理 Tabs -->
    <GlassPanel class="rise-in gov__tabs-panel" body-padding="0">
      <el-tabs v-model="tab" class="gov__tabs">
        <el-tab-pane label="改进候选" name="candidates" />
        <el-tab-pane label="审查报告" name="reports" />
        <el-tab-pane label="灰度开关" name="flags" />
      </el-tabs>

      <!-- 改进候选 -->
      <div v-show="tab === 'candidates'" class="gov__body">
        <div v-for="c in candidates" :key="c.id" class="cand">
          <div class="cand__main">
            <div class="cand__head">
              <span class="mono cand__kind" :class="`is-${c.kind}`">{{ c.kind === 'prompt' ? 'Prompt' : '策略' }}</span>
              <h4 class="cand__title">{{ c.title }}</h4>
              <StatusPill :status="c.status" :text="statusText(c.status)" />
            </div>
            <p class="cand__desc">{{ candidateDesc(c) }}</p>
            <div class="cand__bars">
              <div class="cand__bar-row">
                <span class="cand__bar-label">改进前</span>
                <div class="cand__bar"><span class="cand__bar-fill is-before" :style="{ width: `${c.health_before ?? 0}%` }" /></div>
                <span class="num cand__bar-num">{{ c.health_before }}</span>
              </div>
              <div class="cand__bar-row">
                <span class="cand__bar-label">改进后</span>
                <div class="cand__bar">
                  <span
                    class="cand__bar-fill"
                    :class="(c.health_after ?? 0) >= (c.health_before ?? 0) ? 'is-up' : 'is-down'"
                    :style="{ width: `${c.health_after ?? 0}%` }"
                  />
                </div>
                <span class="num cand__bar-num">{{ c.health_after }}</span>
              </div>
            </div>
          </div>
          <div class="cand__actions">
            <el-button link type="primary" size="small" @click="viewCandidate(c)">查看详情</el-button>
            <template v-if="c.status === 'proposed'">
              <el-button link type="success" size="small" @click="review(c, 'approve')">批准</el-button>
              <el-button link type="danger" size="small" @click="review(c, 'reject')">驳回</el-button>
            </template>
          </div>
        </div>
        <EmptyState v-if="!candidates.length" title="暂无改进候选" />
      </div>

      <!-- 审查报告 -->
      <div v-show="tab === 'reports'" class="gov__body">
        <div v-for="c in candidatesWithReport" :key="c.id" class="report">
          <div class="report__head">
            <h4 class="report__title">{{ c.title }}</h4>
            <StatusPill :status="c.status" :text="statusText(c.status)" />
          </div>
          <p class="report__meta num">Benchmark Run #{{ c.review_report_json?.benchmark_run_id }} · {{ fmtDateTime(c.updated_at) }}</p>
          <ul class="report__findings">
            <li v-for="(f, i) in (c.review_report_json?.findings as string[] | undefined) ?? []" :key="i">
              <el-icon :size="13" :color="c.status === 'rejected' ? 'var(--red)' : 'var(--green)'"><CircleCheckFilled /></el-icon>
              {{ f }}
            </li>
          </ul>
        </div>
        <EmptyState v-if="!candidatesWithReport.length" title="暂无审查报告" />
      </div>

      <!-- 灰度开关 -->
      <div v-show="tab === 'flags'" class="gov__body">
        <div v-for="f in flags" :key="f.flag_key" class="flag">
          <div class="flag__main">
            <div class="flag__head">
              <h4 class="flag__title">{{ f.description }}</h4>
              <span class="flag__scope">影响范围：{{ f.impact_scope }}</span>
            </div>
            <p class="flag__key mono">{{ f.flag_key }} · 更新于 {{ fmtDateTime(f.updated_at) }}</p>
          </div>
          <el-switch
            :model-value="f.enabled"
            :loading="flagSaving === f.flag_key"
            @change="(v: boolean) => toggleFlag(f, v)"
          />
        </div>
        <p class="flag__note">
          <el-icon :size="13"><InfoFilled /></el-icon>
          开启前置：最新成功 Benchmark 健康度须 &gt; {{ THRESHOLD }}（E_EVOLUTION_GATE）
        </p>
      </div>
    </GlassPanel>

    <!-- 候选详情抽屉 -->
    <el-drawer v-model="candDrawer" size="440px" :title="activeCandidate?.title">
      <div v-if="activeCandidate" class="cand-detail">
        <div class="cand-detail__row"><span>类型</span><span class="mono">{{ activeCandidate.kind }}</span></div>
        <div class="cand-detail__row"><span>提交人</span><span>{{ activeCandidate.created_by_name }}</span></div>
        <div class="cand-detail__row"><span>提交时间</span><span class="num">{{ fmtDateTime(activeCandidate.created_at) }}</span></div>
        <div class="cand-detail__row">
          <span>健康度变化</span>
          <span class="num">{{ activeCandidate.health_before }} → {{ activeCandidate.health_after }}</span>
        </div>
        <p class="cand-detail__sec">内容</p>
        <CodeBlock :code="JSON.stringify(activeCandidate.content_json, null, 2)" lang="json" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Aim, CircleCheckFilled, Document, InfoFilled, Lock, VideoPlay, WarnTriangleFilled,
} from '@element-plus/icons-vue'
import type { EChartsOption } from 'echarts'
import {
  benchApi, evolutionApi, ApiError,
  type BenchmarkMetrics, type BenchmarkRun, type EvolutionCandidate, type GrayFlag,
} from '@/api'
import { useProjectStore } from '@/stores/project'
import GlassPanel from '@/components/GlassPanel.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatCard from '@/components/StatCard.vue'
import StatusPill from '@/components/StatusPill.vue'
import EmptyState from '@/components/EmptyState.vue'
import CodeBlock from '@/components/CodeBlock.vue'
import VChart from '@/components/charts/VChart.vue'
import { fmtDateTime } from '@/views/studio/studioUtils'

const THRESHOLD = 90
const projectStore = useProjectStore()
const pid = computed(() => projectStore.currentId ?? 1)

const benchmarks = ref<BenchmarkRun[]>([])
const candidates = ref<EvolutionCandidate[]>([])
const flags = ref<GrayFlag[]>([])
const tab = ref('candidates')
const benchRunning = ref(false)
const flagSaving = ref<string | null>(null)
const candDrawer = ref(false)
const activeCandidate = ref<EvolutionCandidate | null>(null)

/** 最新成功 benchmark 的指标 */
const latestSuccess = computed(() =>
  benchmarks.value
    .filter((b) => b.status === 'succeeded' && b.metrics_json)
    .sort((a, b) => b.id - a.id)[0] ?? null,
)
const metrics = computed<BenchmarkMetrics | null>(() => latestSuccess.value?.metrics_json ?? null)
const health = computed(() => metrics.value?.health_score ?? 0)
const healthy = computed(() => health.value >= THRESHOLD)

function pct(v?: number): string {
  return v === undefined ? '—' : `${(v * 100).toFixed(1)}%`
}

function statusText(s: string): string {
  return { proposed: '待审查', approved: '已批准', rejected: '已驳回' }[s] ?? s
}

function candidateDesc(c: EvolutionCandidate): string {
  const findings = (c.review_report_json?.findings as string[] | undefined) ?? []
  return findings[0] ?? (c.kind === 'prompt' ? 'Schema 推理 Prompt 增加主键识别示例集，强化 PK 推断' : '门禁阈值策略调整')
}

const candidatesWithReport = computed(() => candidates.value.filter((c) => c.review_report_json))

/* ---------- 图表 ---------- */
const gaugeOption = computed<EChartsOption>(() => ({
  series: [
    {
      type: 'gauge',
      startAngle: 210,
      endAngle: -30,
      min: 0,
      max: 100,
      radius: '100%',
      center: ['50%', '62%'],
      progress: {
        show: true,
        width: 14,
        itemStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
            colorStops: [
              { offset: 0, color: '#22d3ee' },
              { offset: 0.55, color: '#818cf8' },
              { offset: 1, color: '#c084fc' },
            ],
          },
          shadowColor: 'rgba(34,211,238,0.45)',
          shadowBlur: 14,
        },
      },
      axisLine: { lineStyle: { width: 14, color: [[1, 'rgba(148,163,184,0.12)']] } },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
      pointer: { show: false },
      anchor: { show: false },
      title: { show: true, offsetCenter: [0, '32%'], color: '#5b6b83', fontSize: 12 },
      detail: {
        valueAnimation: true,
        offsetCenter: [0, '-4%'],
        formatter: (v: number) => `${v.toFixed(0)}`,
        color: '#e6edf7',
        fontSize: 44,
        fontWeight: 600,
        fontFamily: 'JetBrains Mono, monospace',
      },
      data: [{ value: health.value, name: '分' }],
    },
  ],
}))

const trendOption = computed<EChartsOption>(() => {
  const list = [...benchmarks.value]
    .filter((b) => b.metrics_json)
    .sort((a, b) => a.id - b.id)
    .slice(-10)
  return {
    grid: { left: 40, right: 44, top: 20, bottom: 28 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: list.map((_, i) => `#${i + 1}`), boundaryGap: false },
    yAxis: { type: 'value', min: 84, max: 100 },
    series: [
      {
        name: '健康度',
        type: 'line',
        smooth: true,
        data: list.map((b) => ({
          value: b.metrics_json!.health_score,
          itemStyle: { color: b.metrics_json!.health_score >= THRESHOLD ? '#34d399' : '#fb7185' },
        })),
        lineStyle: { width: 2.4, color: '#22d3ee' },
        symbolSize: 7,
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: '#fb7185', type: 'dashed', width: 1.4 },
          label: { color: '#fb7185', formatter: `阈值 ${THRESHOLD} 分`, position: 'insideEndTop' },
          data: [{ yAxis: THRESHOLD }],
        },
      },
    ],
  }
})

/* ---------- 数据 ---------- */
async function loadAll() {
  const [b, c, f] = await Promise.all([
    benchApi.list({ limit: 10 }),
    evolutionApi.listCandidates({ project_id: pid.value, page_size: 50 }),
    evolutionApi.listGrayFlags(pid.value),
  ])
  benchmarks.value = b
  candidates.value = c.items
  flags.value = f
}

async function runBenchmark() {
  benchRunning.value = true
  try {
    const resp = await benchApi.run('v1.0')
    // 轮询至完成（mock 5s 时间线）
    const timer = setInterval(async () => {
      const b = await benchApi.get(resp.benchmark_run_id)
      if (b.status !== 'running') {
        clearInterval(timer)
        benchRunning.value = false
        ElMessage.success(`评测完成 · 健康度 ${b.metrics_json?.health_score ?? '—'}`)
        await loadAll()
      }
    }, 1000)
  } catch (err) {
    benchRunning.value = false
    ElMessage.error(err instanceof Error ? err.message : '评测触发失败')
  }
}

function viewCandidate(c: EvolutionCandidate) {
  activeCandidate.value = c
  candDrawer.value = true
}

async function review(c: EvolutionCandidate, decision: 'approve' | 'reject') {
  await ElMessageBox.confirm(
    `确认${decision === 'approve' ? '批准' : '驳回'}候选「${c.title}」？评审结果写入审计账本。`,
    '评审确认',
    { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' },
  )
  await evolutionApi.review(c.id, { decision })
  ElMessage.success(decision === 'approve' ? '已批准，进入灰度准入流程' : '已驳回')
  await loadAll()
}

async function toggleFlag(f: GrayFlag, enabled: boolean) {
  flagSaving.value = f.flag_key
  try {
    await evolutionApi.updateGrayFlag({ project_id: pid.value, flag_key: f.flag_key, enabled })
    f.enabled = enabled
    ElMessage.success(`已${enabled ? '开启' : '关闭'} ${f.description}`)
  } catch (err) {
    if (err instanceof ApiError && err.code === 'E_EVOLUTION_GATE') {
      ElMessage.error(`准入拦截：${err.message}`)
    } else {
      ElMessage.error(err instanceof Error ? err.message : '更新失败')
    }
  } finally {
    flagSaving.value = null
  }
}

onMounted(async () => {
  if (!projectStore.loaded) await projectStore.fetchList()
  await loadAll()
})
</script>

<style scoped>
.gov__stats {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 14px;
  margin-bottom: 16px;
}
.gov__grid {
  display: grid;
  grid-template-columns: 4fr 8fr;
  gap: 16px;
  margin-bottom: 16px;
}
.gov__health-status {
  margin: 0;
  text-align: center;
  font-size: 13.5px;
}
.gov__health-status.is-ok { color: var(--green); }
.gov__health-status.is-bad { color: var(--red); }
.gov__health-note { display: block; font-size: 12px; color: var(--txt-2); margin-top: 2px; }

.gov__tabs { padding: 0 20px; }
.gov__tabs :deep(.el-tabs__header) { margin-bottom: 0; }
.gov__body { padding: 20px; display: flex; flex-direction: column; gap: 14px; }

/* 候选 */
.cand {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: rgba(148, 163, 184, 0.04);
}
.cand__main { flex: 1; min-width: 0; }
.cand__head { display: flex; align-items: center; gap: 10px; }
.cand__kind {
  padding: 1px 8px;
  border-radius: var(--r-sm);
  font-size: 11px;
  border: 1px solid;
}
.cand__kind.is-prompt { color: var(--violet); border-color: rgba(167, 139, 250, 0.4); background: rgba(167, 139, 250, 0.1); }
.cand__kind.is-policy { color: var(--blue); border-color: rgba(96, 165, 250, 0.4); background: rgba(96, 165, 250, 0.1); }
.cand__title { margin: 0; font-size: 14.5px; }
.cand__desc { margin: 8px 0 0; font-size: 12.5px; color: var(--txt-2); }
.cand__bars { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; max-width: 460px; }
.cand__bar-row { display: grid; grid-template-columns: 52px 1fr 42px; align-items: center; gap: 10px; }
.cand__bar-label { font-size: 11.5px; color: var(--txt-2); }
.cand__bar {
  height: 8px;
  border-radius: 4px;
  background: rgba(148, 163, 184, 0.12);
  overflow: hidden;
}
.cand__bar-fill { display: block; height: 100%; border-radius: 4px; }
.cand__bar-fill.is-before { background: rgba(148, 163, 184, 0.45); }
.cand__bar-fill.is-up { background: linear-gradient(90deg, #34d399, #22d3ee); box-shadow: 0 0 10px rgba(52, 211, 153, 0.4); }
.cand__bar-fill.is-down { background: linear-gradient(90deg, #fb7185, #fbbf24); }
.cand__bar-num { font-size: 12px; color: var(--txt-1); text-align: right; }
.cand__actions { display: flex; gap: 4px; flex: none; }

/* 报告 */
.report {
  padding: 16px 18px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: rgba(148, 163, 184, 0.04);
}
.report__head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.report__title { margin: 0; font-size: 14.5px; }
.report__meta { margin: 6px 0 0; font-size: 12px; color: var(--txt-2); }
.report__findings { margin: 12px 0 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 8px; }
.report__findings li { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--txt-0); }

/* 灰度开关 */
.flag {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: rgba(148, 163, 184, 0.04);
}
.flag__head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.flag__title { margin: 0; font-size: 14.5px; }
.flag__scope { font-size: 12px; color: var(--cyan); }
.flag__key { margin: 6px 0 0; font-size: 12px; color: var(--txt-2); }
.flag__note {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: 12px;
  color: var(--txt-2);
}

.cand-detail { display: flex; flex-direction: column; gap: 12px; }
.cand-detail__row { display: flex; justify-content: space-between; font-size: 13px; color: var(--txt-1); }
.cand-detail__sec { margin: 8px 0 0; font-size: 13px; color: var(--txt-2); }

@media (max-width: 1200px) {
  .gov__stats { grid-template-columns: repeat(3, 1fr); }
  .gov__grid { grid-template-columns: 1fr; }
}
</style>
