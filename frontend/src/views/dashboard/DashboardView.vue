<template>
  <div class="dash">
    <PageHeader title="总览工作台" subtitle="项目健康度、运行趋势与待办一览" />

    <!-- 指标带 -->
    <div class="dash__stats rise-in">
      <StatCard
        label="总连接数"
        :value="connTotal"
        :icon="Coin"
        accent="var(--cyan)"
        :hint="`已连通 ${connOk} · 不可达 ${connBad}`"
        :trend="[18, 19, 20, 20, 22, 23, connTotal]"
      />
      <StatCard
        label="Pipeline 总数"
        :value="pipelineTotal"
        :icon="Share"
        accent="var(--violet)"
        hint="本周新增 4 条"
        :trend="[41, 44, 47, 49, 52, 55, pipelineTotal]"
      />
      <StatCard
        label="待审批"
        :value="pendingPreps"
        :icon="Stamp"
        accent="var(--amber)"
        hint="较昨日 +3 · 需尽快处理"
      />
      <StatCard
        label="今日运行成功率"
        :value="successRate"
        :icon="TrendCharts"
        accent="var(--green)"
        :delta="0.4"
        :format="(v: number | string) => `${v}%`"
        :trend="[96.2, 97.1, 95.8, 98.9, 97.4, 98.2, 98.6]"
      />
    </div>

    <div class="dash__grid">
      <!-- 近 7 天运行趋势 -->
      <GlassPanel class="dash__trend rise-in" title="近 7 天运行趋势" subtitle="成功 / 失败运行数">
        <VChart :option="trendOption" :height="300" />
      </GlassPanel>

      <!-- 待办审批 -->
      <GlassPanel class="dash__todo rise-in" title="待办事项 · 待审批" :subtitle="`${pendingPreps} 条`">
        <template #actions>
          <router-link class="dash__more" :to="`/p/${pid}/runs`">查看全部 ›</router-link>
        </template>
        <div v-if="todoList.length" class="todo">
          <div v-for="p in todoList" :key="p.id" class="todo__item hover-lift">
            <div class="todo__main">
              <p class="todo__title">{{ p.pipeline_name }}</p>
              <div class="todo__meta">
                <RiskTag :level="p.risk_level" />
                <span class="todo__wait">等待{{ p.approval_requests.find((a) => a.status === 'pending')?.required_role === 'checker2' ? '安全审批人' : '数据审批人' }}</span>
              </div>
              <p class="todo__actor">
                <span class="todo__avatar">{{ (p.maker_name ?? '?').slice(0, 1) }}</span>
                {{ p.maker_name }} · {{ fmtDateTime(p.created_at) }}
              </p>
            </div>
            <el-button type="primary" size="small" plain @click="router.push(`/p/${pid}/runs`)">去审批</el-button>
          </div>
        </div>
        <EmptyState v-else title="暂无待审批事项" description="所有准备单均已处理完毕" />
      </GlassPanel>
    </div>

    <div class="dash__grid dash__grid--bottom">
      <!-- Doris 存储 -->
      <GlassPanel class="rise-in" title="Doris 存储用量" :icon="''">
        <div class="quota">
          <p class="quota__num"><span class="num">1.2</span> <span class="quota__unit">TB / 2 TB</span></p>
          <el-progress :percentage="60" :stroke-width="8" :show-text="false" color="#22d3ee" />
          <p class="quota__hint">已用 60% · 3 个租户 · raw 区 412 GB · shadow 区 96 GB</p>
        </div>
      </GlassPanel>

      <!-- MinIO 文件资产 -->
      <GlassPanel class="rise-in" title="MinIO 文件资产">
        <div class="quota">
          <p class="quota__num"><span class="num">8,412</span> <span class="quota__unit">个文件对象</span></p>
          <div class="quota__tags">
            <span class="quota__tag">CSV 6,204</span>
            <span class="quota__tag">Parquet 2,208</span>
          </div>
          <p class="quota__hint">今日新增 +126 · 解析失败 2</p>
        </div>
      </GlassPanel>

      <!-- 活跃 Pipeline Top5 -->
      <GlassPanel class="rise-in" title="近期活跃 Pipeline Top5" subtitle="近 7 天 · 按运行次数">
        <ol class="top5">
          <li v-for="(t, i) in top5" :key="t.name" class="top5__row">
            <span class="top5__rank num">{{ i + 1 }}</span>
            <span class="top5__name">{{ t.name }}</span>
            <span class="top5__count">
              <span class="dot" :style="{ background: t.ok ? 'var(--green)' : 'var(--red)' }" />
              <span class="num">{{ t.count }} 次</span>
            </span>
          </li>
        </ol>
      </GlassPanel>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Coin, Share, Stamp, TrendCharts } from '@element-plus/icons-vue'
import type { EChartsOption } from 'echarts'
import { connApi, pipelineApi, prepApi, runApi, type ExecutionRun, type Preparation } from '@/api'
import { useProjectStore } from '@/stores/project'
import GlassPanel from '@/components/GlassPanel.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatCard from '@/components/StatCard.vue'
import RiskTag from '@/components/RiskTag.vue'
import EmptyState from '@/components/EmptyState.vue'
import VChart from '@/components/charts/VChart.vue'
import { fmtDateTime } from '@/views/studio/studioUtils'

const router = useRouter()
const projectStore = useProjectStore()
const pid = computed(() => projectStore.currentId ?? 1)

const connTotal = ref(0)
const connOk = ref(0)
const connBad = ref(0)
const pipelineTotal = ref(0)
const pendingPreps = ref(0)
const todoList = ref<Preparation[]>([])
const runs = ref<ExecutionRun[]>([])

const successRate = computed(() => {
  const finished = runs.value.filter((r) => ['succeeded', 'failed'].includes(r.status))
  if (!finished.length) return 98.6
  const ok = finished.filter((r) => r.status === 'succeeded').length
  return Math.round((ok / finished.length) * 1000) / 10
})

/** 近 7 天成功/失败运行数 */
const trendOption = computed<EChartsOption>(() => {
  const days: string[] = []
  const ok: number[] = []
  const bad: number[] = []
  for (let i = 6; i >= 0; i--) {
    const d = new Date(Date.now() - i * 86_400_000)
    const key = `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    days.push(key)
    const dayRuns = runs.value.filter((r) => {
      const t = r.started_at ?? r.created_at
      if (!t) return false
      const rd = new Date(t)
      return rd.getMonth() === d.getMonth() && rd.getDate() === d.getDate()
    })
    ok.push(dayRuns.filter((r) => r.status === 'succeeded').length)
    bad.push(dayRuns.filter((r) => r.status === 'failed').length)
  }
  return {
    grid: { left: 40, right: 16, top: 36, bottom: 28 },
    legend: { data: ['成功', '失败'], top: 0, right: 0 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: days, boundaryGap: false },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      {
        name: '成功',
        type: 'line',
        smooth: true,
        data: ok,
        lineStyle: { width: 2.4, color: '#34d399' },
        itemStyle: { color: '#34d399' },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(52,211,153,0.22)' },
              { offset: 1, color: 'rgba(52,211,153,0)' },
            ],
          },
        },
      },
      {
        name: '失败',
        type: 'line',
        smooth: true,
        data: bad,
        lineStyle: { width: 2.4, color: '#fb7185' },
        itemStyle: { color: '#fb7185' },
      },
    ],
  }
})

const top5 = [
  { name: 'orders 增量同步 → Doris', count: 23, ok: true },
  { name: 'user_center 全量归档', count: 18, ok: true },
  { name: 'refund 退款明细清洗', count: 15, ok: false },
  { name: 'dim_region 维表同步', count: 12, ok: true },
  { name: 'crm_contract 合同抽取', count: 9, ok: true },
]

onMounted(async () => {
  if (!projectStore.loaded) await projectStore.fetchList()
  const [conns, pipelines, preps, runPage] = await Promise.all([
    connApi.list(pid.value, { page_size: 100 }),
    pipelineApi.list(pid.value, { page_size: 100 }),
    prepApi.list(pid.value, { status: 'pending', page_size: 5 }),
    runApi.list(pid.value, { page_size: 100 }),
  ])
  connTotal.value = conns.total
  connOk.value = conns.items.filter((c) => c.status === 'connected').length
  connBad.value = conns.items.filter((c) => c.status === 'unreachable').length
  pipelineTotal.value = pipelines.total
  pendingPreps.value = preps.total
  todoList.value = preps.items
  runs.value = runPage.items
})
</script>

<style scoped>
.dash__stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.dash__grid {
  display: grid;
  grid-template-columns: 7fr 5fr;
  gap: 16px;
  margin-bottom: 16px;
}
.dash__grid--bottom { grid-template-columns: 1fr 1fr 1.4fr; margin-bottom: 0; }

.dash__more { font-size: 12px; }

.todo { display: flex; flex-direction: column; gap: 12px; }
.todo__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: rgba(148, 163, 184, 0.05);
}
.todo__title { margin: 0; font-size: 13.5px; color: var(--txt-0); }
.todo__meta { display: flex; align-items: center; gap: 8px; margin-top: 6px; }
.todo__wait { font-size: 12px; color: var(--amber); }
.todo__actor { display: flex; align-items: center; gap: 6px; margin: 6px 0 0; font-size: 12px; color: var(--txt-2); }
.todo__avatar {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 11px;
  color: #fff;
  background: var(--grad);
}

.quota__num { margin: 0; font-size: 30px; font-weight: 600; }
.quota__unit { font-size: 13px; color: var(--txt-2); font-weight: 400; }
.quota__hint { margin: 10px 0 0; font-size: 12px; color: var(--txt-2); }
.quota__tags { display: flex; gap: 8px; margin-top: 12px; }
.quota__tag {
  padding: 2px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  font-size: 12px;
  color: var(--txt-1);
  background: rgba(148, 163, 184, 0.07);
}

.top5 { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; }
.top5__row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 4px;
  border-bottom: 1px dashed var(--line);
}
.top5__row:last-child { border-bottom: none; }
.top5__rank { width: 18px; color: var(--txt-2); font-size: 13px; }
.top5__name { flex: 1; font-size: 13px; color: var(--txt-0); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.top5__count { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--txt-1); }

@media (max-width: 1200px) {
  .dash__stats { grid-template-columns: repeat(2, 1fr); }
  .dash__grid, .dash__grid--bottom { grid-template-columns: 1fr; }
}
</style>
