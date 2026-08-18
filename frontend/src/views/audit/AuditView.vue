<template>
  <div class="audit">
    <PageHeader title="审计" subtitle="平台全量操作记录与证据账本 · 只读视图">
      <template #actions><span class="audit__readonly">只读</span></template>
    </PageHeader>

    <!-- 筛选 + 事件表 -->
    <GlassPanel class="rise-in" body-padding="0">
      <div class="audit__filters">
        <el-date-picker
          v-model="range"
          type="datetimerange"
          range-separator="~"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          size="default"
          style="width: 340px"
        />
        <el-select v-model="eventType" placeholder="事件类型：全部" clearable style="width: 170px">
          <el-option v-for="(meta, t) in EVENT_META" :key="t" :label="meta.label" :value="t" />
        </el-select>
        <el-input
          v-model="keyword"
          placeholder="搜索资源ID / 操作人 / 摘要关键词…"
          clearable
          style="width: 280px"
          @keyup.enter="search"
        />
        <el-button type="primary" :icon="Search" @click="search">查询</el-button>
        <el-button :icon="Download" @click="exportCsv">导出</el-button>
      </div>

      <el-table :data="events" v-loading="loading">
        <el-table-column label="时间" width="160">
          <template #default="{ row }"><span class="num">{{ fmtFull(row.created_at) }}</span></template>
        </el-table-column>
        <el-table-column label="操作人" width="90">
          <template #default="{ row }">{{ row.actor_name }}</template>
        </el-table-column>
        <el-table-column label="事件类型" width="120">
          <template #default="{ row }">
            <span class="evt-tag" :style="evtStyle(row.event_type)">{{ evtLabel(row.event_type) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="资源类型" width="110">
          <template #default="{ row }"><span style="text-transform: capitalize">{{ row.resource_type ?? '—' }}</span></template>
        </el-table-column>
        <el-table-column label="资源ID" width="130">
          <template #default="{ row }"><span class="mono" style="color: var(--cyan)">{{ row.resource_id ?? '—' }}</span></template>
        </el-table-column>
        <el-table-column label="事件摘要" min-width="260">
          <template #default="{ row }">{{ row.summary }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-popover placement="left" :width="380" trigger="click">
              <template #reference>
                <el-button link type="primary" size="small">查看</el-button>
              </template>
              <div class="evt-detail">
                <p class="evt-detail__summary">{{ row.summary }}</p>
                <div class="evt-detail__row"><span>event_hash</span><HashChip :hash="row.event_hash" :head="8" :tail="6" /></div>
                <div class="evt-detail__row"><span>prev_event_hash</span><HashChip :hash="row.prev_event_hash" :head="8" :tail="6" /></div>
                <div class="evt-detail__row"><span>actor</span><span>{{ row.actor_name }} (id: {{ row.actor_id }})</span></div>
                <div class="evt-detail__row"><span>时间</span><span class="num">{{ fmtFull(row.created_at) }}</span></div>
              </div>
            </el-popover>
          </template>
        </el-table-column>
      </el-table>

      <div class="audit__pager">
        <span class="audit__total">共 <span class="num">{{ total.toLocaleString() }}</span> 条审计事件</span>
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next"
          background
          @current-change="load"
        />
      </div>
    </GlassPanel>

    <!-- 证据账本校验 -->
    <GlassPanel class="rise-in audit__ledger" body-padding="20px">
      <div class="ledger__head">
        <div class="ledger__title-wrap">
          <span class="ledger__shield" :class="verify?.ok === false ? 'is-broken' : ''">
            <el-icon :size="20"><Lock /></el-icon>
          </span>
          <div>
            <h3 class="ledger__title">
              证据账本完整性校验
              <span v-if="verify && !verify.ok" class="ledger__broken-tag">检测到篡改 · 断点 BLK-0042</span>
              <span v-else-if="verify?.ok" class="ledger__ok-tag">链式完整</span>
            </h3>
            <p class="ledger__meta">
              上次校验：{{ fmtFull(lastVerifyAt) }} · 校验人：系统定时任务 · 共
              <span class="num">{{ (verify?.checked_events ?? 0).toLocaleString() }}</span> 个区块 ·
              <span class="num">{{ ((verify?.checked_events ?? 1) - 1).toLocaleString() }}</span> 个通过
            </p>
          </div>
        </div>
        <div class="ledger__actions">
          <el-button type="primary" :icon="Refresh" :loading="verifying" @click="doVerify">发起校验</el-button>
          <el-button text :icon="chainOpen ? ArrowUp : ArrowDown" @click="chainOpen = !chainOpen">
            {{ chainOpen ? '收起账本详情' : '展开账本详情' }}
          </el-button>
        </div>
      </div>

      <el-collapse-transition>
        <div v-show="chainOpen">
          <!-- 区块链可视化 -->
          <div class="chain">
            <template v-for="(b, i) in chainBlocks" :key="b.label">
              <div class="chain__block" :class="{ 'is-broken': b.broken }">
                <p class="chain__label mono">{{ b.label }}</p>
                <div class="chain__row">
                  <span class="chain__key">prev_event_hash</span>
                  <span class="mono chain__hash" :class="{ 'is-bad': b.broken }">{{ b.prev }}</span>
                </div>
                <div class="chain__row">
                  <span class="chain__key">event_hash</span>
                  <span class="mono chain__hash">{{ b.hash }}</span>
                </div>
                <span class="chain__dot" :class="b.broken ? 'is-bad' : 'is-ok'" />
              </div>
              <div v-if="i < chainBlocks.length - 1" class="chain__link" :class="{ 'is-broken': chainBlocks[i + 1].broken }">
                <el-icon :size="13"><Link /></el-icon>
              </div>
            </template>
          </div>

          <el-alert
            v-if="verify && !verify.ok"
            type="error"
            :closable="false"
            show-icon
            class="chain__alert"
            :title="`链式校验失败：BLK-0042.prev_event_hash（${shortHash(verify.actual_hash)}）≠ BLK-0041.event_hash（${shortHash(verify.expected_hash)}），断点之后的事件可信度存疑，已自动冻结审计导出并通知安全审批人。`"
          />
        </div>
      </el-collapse-transition>
    </GlassPanel>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, ArrowUp, Download, Link, Lock, Refresh, Search } from '@element-plus/icons-vue'
import { auditApi, type AuditEvent, type VerifyResult } from '@/api'
import { useProjectStore } from '@/stores/project'
import GlassPanel from '@/components/GlassPanel.vue'
import PageHeader from '@/components/PageHeader.vue'
import HashChip from '@/components/HashChip.vue'

const projectStore = useProjectStore()

const EVENT_META: Record<string, { label: string; color: string }> = {
  'run.start': { label: '运行启动', color: 'var(--blue)' },
  'run.succeed': { label: '运行成功', color: 'var(--green)' },
  'run.fail': { label: '运行失败', color: 'var(--red)' },
  'run.cancel': { label: '运行取消', color: 'var(--txt-2)' },
  'run.rollback': { label: '受管回滚', color: 'var(--amber)' },
  'run.rerun': { label: '安全重跑', color: 'var(--cyan)' },
  'run.dry_run': { label: 'Dry-Run', color: 'var(--violet)' },
  'preparation.submit': { label: '提交审批', color: 'var(--cyan)' },
  'preparation.freeze': { label: '冻结准备单', color: 'var(--violet)' },
  'approval.approve': { label: '审批通过', color: 'var(--green)' },
  'approval.reject': { label: '审批拒绝', color: 'var(--red)' },
  'token.issue': { label: '令牌签发', color: 'var(--green)' },
  'config.change': { label: '配置变更', color: 'var(--amber)' },
  'connection.test': { label: '连接测试', color: 'var(--blue)' },
  'connection.create': { label: '创建连接', color: 'var(--blue)' },
  'file.upload': { label: '上传文件', color: 'var(--cyan)' },
  'file.delete': { label: '删除文件', color: 'var(--red)' },
  'metadata.profile': { label: '元数据探查', color: 'var(--violet)' },
  'pipeline.create': { label: '创建 Pipeline', color: 'var(--cyan)' },
  'generation.trigger': { label: '触发生成', color: 'var(--violet)' },
  'generation.answer': { label: '澄清回答', color: 'var(--violet)' },
  'version.freeze': { label: '冻结版本', color: 'var(--cyan)' },
  'benchmark.run': { label: 'Benchmark', color: 'var(--blue)' },
  'evolution.propose': { label: '进化提案', color: 'var(--amber)' },
  'evolution.review': { label: '进化评审', color: 'var(--amber)' },
  'evolution.gray_flag': { label: '灰度开关', color: 'var(--amber)' },
}

const events = ref<AuditEvent[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 10
const loading = ref(false)
const range = ref<[Date, Date] | null>(null)
const eventType = ref('')
const keyword = ref('')

const verify = ref<VerifyResult | null>(null)
const verifying = ref(false)
const chainOpen = ref(true)
const lastVerifyAt = ref<string>(new Date(Date.now() - 3 * 3_600_000).toISOString())

function evtLabel(t: string): string {
  return EVENT_META[t]?.label ?? t
}
function evtStyle(t: string) {
  const c = EVENT_META[t]?.color ?? 'var(--txt-1)'
  return {
    color: c,
    borderColor: `color-mix(in srgb, ${c} 40%, transparent)`,
    background: `color-mix(in srgb, ${c} 10%, transparent)`,
  }
}

function fmtFull(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function shortHash(h?: string | null): string {
  if (!h) return '—'
  return `${h.slice(0, 4)}…${h.slice(-4)}`
}

async function load() {
  loading.value = true
  try {
    const resp = await auditApi.events({
      project_id: projectStore.currentId ?? 1,
      event_type: eventType.value || undefined,
      keyword: keyword.value || undefined,
      from: range.value?.[0]?.toISOString(),
      to: range.value?.[1]?.toISOString(),
      page: page.value,
      page_size: pageSize,
    })
    events.value = resp.items
    total.value = resp.total
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

/* ---------- 账本链可视化（取最近 6 个区块，按 verify 结果标记断点） ---------- */
interface ChainBlock { label: string; prev: string; hash: string; broken: boolean }

const chainBlocks = computed<ChainBlock[]>(() => {
  // 旧 → 新 排列，取含 BLK-0042 附近的窗口；找不到则取头部 6 个
  const ordered = [...events.value].reverse()
  let pool = ordered.filter((e) => /^BLK-/.test(e.resource_id ?? ''))
  const brokenIdx = pool.findIndex((e) => e.resource_id === 'BLK-0042')
  let window: AuditEvent[]
  if (brokenIdx >= 0) {
    const start = Math.max(0, brokenIdx - 3)
    window = pool.slice(start, start + 6)
  } else {
    window = pool.slice(0, 6)
  }
  if (!window.length) {
    // 筛选条件下无 BLK 样本时的兜底展示
    return [
      { label: 'BLK-0039', prev: '7d51…e90a', hash: 'b844…1f72', broken: false },
      { label: 'BLK-0040', prev: 'b844…1f72', hash: '3c9a…d517', broken: false },
      { label: 'BLK-0041', prev: '3c9a…d517', hash: '9f2e…c21d', broken: false },
      { label: 'BLK-0042', prev: 'a1c4…88be', hash: '55f0…3aa9', broken: verify.value?.ok === false },
      { label: 'BLK-0043', prev: '55f0…3aa9', hash: '0e7b…f6c4', broken: false },
      { label: 'BLK-0044', prev: '0e7b…f6c4', hash: '62d8…9b01', broken: false },
    ]
  }
  return window.map((e) => ({
    label: e.resource_id ?? `EVT-${e.id}`,
    prev: shortHash(e.prev_event_hash),
    hash: shortHash(e.event_hash),
    broken: verify.value?.ok === false && e.resource_id === 'BLK-0042',
  }))
})

async function doVerify() {
  verifying.value = true
  try {
    verify.value = await auditApi.verify(projectStore.currentId ?? 1)
    lastVerifyAt.value = new Date().toISOString()
    chainOpen.value = true
    if (verify.value.ok) {
      ElMessage.success('账本链式完整，未发现篡改')
    } else {
      ElMessage.error(`检测到篡改：断点事件 #${verify.value.broken_at_event_id}，审计导出已自动冻结`)
    }
  } finally {
    verifying.value = false
  }
}

/* ---------- 导出 ---------- */
function exportCsv() {
  if (verify.value && !verify.value.ok) {
    ElMessage.error('账本存在篡改断点，审计导出已被自动冻结')
    return
  }
  const header = 'time,actor,event_type,resource_type,resource_id,summary,event_hash\n'
  const rows = events.value
    .map((e) =>
      [e.created_at, e.actor_name, e.event_type, e.resource_type ?? '', e.resource_id ?? '', `"${e.summary.replace(/"/g, '""')}"`, e.event_hash].join(','),
    )
    .join('\n')
  const blob = new Blob(['﻿' + header + rows], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `audit-events-p${page.value}.csv`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('已导出当前页审计事件')
}

onMounted(async () => {
  if (!projectStore.loaded) await projectStore.fetchList()
  await load()
  await doVerify()
})
</script>

<style scoped>
.audit__readonly {
  padding: 2px 10px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-sm);
  font-size: 12px;
  color: var(--txt-2);
}

.audit__filters {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--line);
  flex-wrap: wrap;
}

.evt-tag {
  padding: 1px 9px;
  border: 1px solid;
  border-radius: var(--r-sm);
  font-size: 12px;
  white-space: nowrap;
}

.evt-detail { display: flex; flex-direction: column; gap: 10px; }
.evt-detail__summary { margin: 0; font-size: 13px; color: var(--txt-0); }
.evt-detail__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 12.5px;
  color: var(--txt-2);
}

.audit__pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
}
.audit__total { font-size: 12.5px; color: var(--txt-2); }

/* ---------- 账本 ---------- */
.audit__ledger { margin-top: 16px; }
.ledger__head { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.ledger__title-wrap { display: flex; align-items: center; gap: 14px; }
.ledger__shield {
  width: 44px;
  height: 44px;
  border-radius: var(--r-md);
  display: grid;
  place-items: center;
  color: var(--green);
  border: 1px solid rgba(52, 211, 153, 0.35);
  background: rgba(52, 211, 153, 0.08);
}
.ledger__shield.is-broken {
  color: var(--red);
  border-color: rgba(251, 113, 133, 0.4);
  background: rgba(251, 113, 133, 0.08);
  box-shadow: 0 0 20px rgba(251, 113, 133, 0.2);
}
.ledger__title { font-size: 16px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ledger__broken-tag {
  padding: 1px 10px;
  border-radius: var(--r-sm);
  font-size: 12px;
  color: var(--red);
  border: 1px solid rgba(251, 113, 133, 0.45);
  background: rgba(251, 113, 133, 0.12);
}
.ledger__ok-tag {
  padding: 1px 10px;
  border-radius: var(--r-sm);
  font-size: 12px;
  color: var(--green);
  border: 1px solid rgba(52, 211, 153, 0.45);
  background: rgba(52, 211, 153, 0.12);
}
.ledger__meta { margin: 4px 0 0; font-size: 12.5px; color: var(--txt-2); }
.ledger__actions { display: flex; align-items: center; gap: 8px; }

.chain {
  display: flex;
  align-items: stretch;
  gap: 0;
  margin-top: 20px;
  overflow-x: auto;
  padding-bottom: 6px;
}
.chain__block {
  position: relative;
  flex: 1 0 150px;
  min-width: 150px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: rgba(148, 163, 184, 0.05);
  transition: border-color 0.25s, box-shadow 0.25s;
}
.chain__block.is-broken {
  border-color: rgba(251, 113, 133, 0.55);
  background: rgba(251, 113, 133, 0.07);
  box-shadow: 0 0 18px rgba(251, 113, 133, 0.18);
}
.chain__label { margin: 0 0 8px; font-size: 13px; color: var(--txt-0); font-weight: 600; }
.chain__row { display: flex; flex-direction: column; margin-bottom: 6px; }
.chain__key { font-size: 10.5px; color: var(--txt-2); letter-spacing: 0.04em; }
.chain__hash { font-size: 12px; color: var(--txt-1); }
.chain__hash.is-bad { color: var(--red); text-decoration: line-through; }
.chain__dot {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.chain__dot.is-ok { background: var(--green); box-shadow: 0 0 8px rgba(52, 211, 153, 0.6); }
.chain__dot.is-bad { background: var(--red); box-shadow: 0 0 8px rgba(251, 113, 133, 0.7); }
.chain__link {
  display: grid;
  place-items: center;
  width: 30px;
  flex: none;
  color: var(--txt-2);
}
.chain__link.is-broken { color: var(--red); }

.chain__alert { margin-top: 16px; }
</style>
