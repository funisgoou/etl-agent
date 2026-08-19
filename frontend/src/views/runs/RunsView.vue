<template>
  <div class="runs">
    <PageHeader title="运行中心" subtitle="四眼审批 · 执行监控 · 受管运维操作" />

    <!-- ================= 待我审批 ================= -->
    <section class="rise-in">
      <div class="runs__sec-head">
        <h3 class="runs__sec-title">待我审批 <span class="runs__sec-num num">{{ pendingPreps.length }}</span></h3>
        <el-radio-group v-model="approvalFilter" size="small">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="checker1">数据审批人</el-radio-button>
          <el-radio-button value="checker2">安全审批人</el-radio-button>
        </el-radio-group>
      </div>

      <div v-if="filteredPreps.length" class="runs__preps">
        <div v-for="p in filteredPreps" :key="p.id" class="prep-card hover-lift">
          <div class="prep-card__top">
            <RiskTag :level="p.risk_level" />
            <span class="mono prep-card__code">{{ p.code }}</span>
            <StatusPill :status="p.status" text="审批中" />
          </div>
          <h4 class="prep-card__title">{{ p.pipeline_name }}</h4>
          <p class="prep-card__applicant">申请人：{{ p.maker_name }} · {{ fmtDateTime(p.created_at) }}</p>
          <div class="prep-card__scope mono">
            {{ scopeText(p) }}
          </div>
          <p class="prep-card__est num">
            预估 ≈ {{ Number(p.impact_json.estimated_rows ?? 0).toLocaleString() }} 行 · {{ p.budget_json.max_credits ?? '—' }} credits
          </p>
          <div class="prep-card__foot">
            <a class="prep-card__detail" @click="openApproval(p, true)">查看详情 ›</a>
            <el-tooltip
              v-if="listDenyReason(p)"
              :content="listDenyReason(p)"
              placement="top"
            >
              <span>
                <el-button type="primary" size="small" disabled>审批</el-button>
              </span>
            </el-tooltip>
            <el-button v-else type="primary" size="small" @click="openApproval(p)">审批</el-button>
          </div>
        </div>
      </div>
      <GlassPanel v-else>
        <EmptyState title="暂无待审批准备单" description="四眼审批流中的准备单会出现在这里" />
      </GlassPanel>
    </section>

    <!-- ================= 执行监控 ================= -->
    <section class="rise-in" style="margin-top: 22px">
      <div class="runs__sec-head">
        <h3 class="runs__sec-title">执行监控</h3>
        <span class="runs__sec-hint">点击运行中任务查看右侧实时详情</span>
      </div>
      <GlassPanel body-padding="0">
        <el-table :data="runList" v-loading="runsLoading" highlight-current-row @row-click="(r: ExecutionRun) => openMonitor(r)">
          <el-table-column label="任务ID" width="130">
            <template #default="{ row }"><span class="mono" style="color: var(--cyan)">RUN-{{ row.id }}</span></template>
          </el-table-column>
          <el-table-column label="Pipeline" min-width="170">
            <template #default="{ row }">{{ row.pipeline_name }}</template>
          </el-table-column>
          <el-table-column label="类型" width="90">
            <template #default="{ row }">
              <span class="runs__kind" :class="row.run_kind === 'dry_run' ? 'is-dry' : ''">
                {{ row.run_kind === 'dry_run' ? 'Dry-Run' : '正式' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }"><StatusPill :status="row.status" /></template>
          </el-table-column>
          <el-table-column label="子阶段" width="110">
            <template #default="{ row }">
              <span v-if="row.sub_stage" class="mono runs__substage">{{ row.sub_stage }}</span>
              <span v-else class="runs__none">—</span>
            </template>
          </el-table-column>
          <el-table-column label="入 / 出 / 错" min-width="170">
            <template #default="{ row }">
              <span class="num">{{ row.input_records ?? '—' }} / {{ row.output_records ?? '—' }} / <span :style="row.error_records ? 'color: var(--red)' : ''">{{ row.error_records ?? '—' }}</span></span>
            </template>
          </el-table-column>
          <el-table-column label="开始时间" width="130">
            <template #default="{ row }"><span class="num">{{ fmtDateTime(row.started_at ?? row.created_at) }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="openMonitor(row)">监控</el-button>
              <el-button
                v-if="isTerminal(row.status)"
                link type="primary" size="small"
                @click.stop="doRerun(row)"
              >重跑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </GlassPanel>
    </section>

    <!-- ================= 审批对话框 ================= -->
    <el-dialog v-model="approvalDialog" width="720px" :show-close="true" class="approval-dlg">
      <template #header>
        <div class="apv__head">
          审批 Preparation <span class="mono" style="color: var(--cyan)">#{{ activePrep?.code }}</span>
          <RiskTag v-if="activePrep" :level="activePrep.risk_level" />
        </div>
      </template>

      <div v-if="activePrep" class="apv">
        <div class="apv__facts">
          <p class="apv__facts-title"><el-icon :size="14"><Lock /></el-icon> 冻结事实 · 只读</p>
          <dl class="apv__kv">
            <div><dt>需求描述</dt><dd>{{ activePrep.pipeline_name }} · {{ scopeText(activePrep) }}</dd></div>
            <div><dt>Schema 映射</dt><dd>12 字段 → 12 字段 · status→order_status、created_at→dt 两处改名 · email/phone/id_card 强制脱敏</dd></div>
            <div><dt>质量规则</dt><dd>status&lt;&gt;'refunded' · email 非空 · 行数一致性硬判据（不匹配即判失败）</dd></div>
            <div><dt>回滚方案</dt><dd>{{ activePrep.rollback_plan_json.steps.join(' → ') }}（保留现场 72h）</dd></div>
            <div><dt>预算配置</dt><dd class="num">{{ activePrep.budget_json.max_credits }} credits · 超时 {{ Math.round((activePrep.budget_json.max_duration_seconds ?? 0) / 60) }}min 自动熔断 · 最大重试 2 次</dd></div>
          </dl>
          <div class="apv__hash">
            <HashChip :hash="activePrep.input_fingerprint" :head="8" :tail="6" />
            <span class="apv__hash-note">input_fingerprint · 冻结于 {{ fmtDateTime(activePrep.created_at) }}</span>
          </div>
        </div>

        <div class="apv__panels">
          <div
            v-for="slot in (['checker1', 'checker2'] as const)"
            :key="slot"
            class="apv__panel"
            :class="{ 'is-active': activeSlot === slot, 'is-locked': slot === 'checker2' && !checker1Done }"
          >
            <div class="apv__panel-head">
              <span>{{ slot === 'checker1' ? '数据审批人' : '安全审批人' }}</span>
              <span class="apv__panel-state">
                {{ slotStateText(slot) }}
              </span>
            </div>
            <template v-if="slotRequest(slot)?.status !== 'decided'">
              <el-radio-group v-model="decisions[slot]" :disabled="slot === 'checker2' && !checker1Done">
                <el-radio value="approve">通过</el-radio>
                <el-radio value="reject">拒绝</el-radio>
              </el-radio-group>
              <el-input
                v-model="comments[slot]"
                type="textarea"
                :rows="2"
                :placeholder="slot === 'checker2' && !checker1Done ? '数据审批通过后开放填写' : '填写审批意见（必填）'"
                :disabled="slot === 'checker2' && !checker1Done"
              />
              <el-checkbox v-model="signed[slot]" :disabled="slot === 'checker2' && !checker1Done">
                已核对冻结事实，电子签名：{{ authStore.displayName }}
              </el-checkbox>
            </template>
            <div v-else class="apv__decided">
              <StatusPill
                :status="slotRequest(slot)?.decision === 'approve' ? 'approved' : 'rejected'"
                :text="slotRequest(slot)?.decision === 'approve' ? '已通过' : '已拒绝'"
              />
              <p class="apv__decided-comment">{{ slotRequest(slot)?.approver_name }}：{{ slotRequest(slot)?.comment || '—' }}</p>
            </div>
          </div>
        </div>

        <p class="apv__cap">
          <el-icon :size="13" color="var(--green)"><CircleCheckFilled /></el-icon>
          双审批通过后，Commit 时签发 Ed25519 单次 Capability（TTL 5 分钟 · 防重放）
        </p>
      </div>

      <template #footer>
        <span class="apv__footer-note">提交需二次确认</span>
        <el-button @click="approvalDialog = false">取消</el-button>
        <el-tooltip
          v-if="approvalDenyReason && activePrep?.status !== 'approved'"
          :content="approvalDenyReason"
          placement="top"
        >
          <span>
            <el-button type="primary" disabled>确认提交审批</el-button>
          </span>
        </el-tooltip>
        <el-button
          v-else-if="activePrep?.status === 'approved'"
          type="success"
          :loading="committing"
          @click="doCommit"
        >Commit 提交执行</el-button>
        <el-button v-else type="primary" :loading="deciding" @click="submitDecision">确认提交审批</el-button>
      </template>
    </el-dialog>

    <!-- ================= 执行监控抽屉 ================= -->
    <el-drawer v-model="monitorOpen" size="560px" :with-header="false" @closed="closeMonitor">
      <div v-if="monitorRun" class="mon">
        <header class="mon__head">
          <div>
            <h3 class="mon__title">
              RUN-{{ monitorRun.id }} <span class="mon__pname">{{ monitorRun.pipeline_name }}</span>
            </h3>
            <div class="mon__meta">
              <StatusPill :status="liveStatus" />
              <span class="mon__kind mono">{{ monitorRun.run_kind === 'dry_run' ? 'Dry-Run · 免四眼' : '正式执行' }}</span>
              <span v-if="stream.state.connected" class="mon__live"><span class="dot is-live" style="background: var(--green)" /> SSE 实时推送中</span>
            </div>
          </div>
          <el-icon class="mon__close" :size="18" @click="monitorOpen = false"><Close /></el-icon>
        </header>

        <!-- 子阶段进度 -->
        <div class="mon__stages">
          <div
            v-for="s in ['COPYING', 'SPLITTING', 'SWAPPING']"
            :key="s"
            class="mon__stage"
            :class="stageClass(s)"
          >
            <span class="mono">{{ s }}</span>
          </div>
        </div>

        <!-- 实时指标 -->
        <div class="mon__metrics">
          <div class="mon__metric">
            <p class="mon__metric-label">写入 shadow 行数</p>
            <p class="mon__metric-value num">{{ liveOutput.toLocaleString() }}</p>
            <p class="mon__metric-sub num">读取 {{ liveInput.toLocaleString() }} 行</p>
          </div>
          <div class="mon__metric">
            <p class="mon__metric-label">吞吐量</p>
            <p class="mon__metric-value num" style="color: var(--cyan)">{{ (stream.state.throughput_rps ?? 0).toLocaleString() }} <span class="mon__metric-unit">行/s</span></p>
            <p class="mon__metric-sub num">{{ fmtBytes(liveBytes) }}</p>
          </div>
          <div class="mon__metric">
            <p class="mon__metric-label">当前拒绝率</p>
            <p class="mon__metric-value num" :style="rejectRate > 0.05 ? 'color: var(--amber)' : 'color: var(--green)'">
              {{ (rejectRate * 100).toFixed(2) }}%
            </p>
            <p class="mon__metric-sub num">拒绝 {{ liveError.toLocaleString() }} 行</p>
          </div>
        </div>

        <!-- 监督守护事件 -->
        <div v-if="stream.state.supervision.length" class="mon__super">
          <p class="mon__sec-title">监督守护</p>
          <div v-for="(s, i) in stream.state.supervision" :key="i" class="mon__super-item" :class="`is-${s.decision}`">
            <el-icon :size="14"><WarningFilled /></el-icon>
            <span class="mono">{{ s.metric }} = {{ s.value }}</span>
            <span class="mon__super-th">阈值 {{ s.threshold }} · {{ s.decision === 'warning' ? '预警（继续观察）' : s.decision }}</span>
          </div>
        </div>

        <!-- 拒绝率趋势 -->
        <div class="mon__chart">
          <p class="mon__sec-title">拒绝率趋势（近 60 分钟）</p>
          <VChart :option="rejectChartOption" :height="150" />
        </div>

        <!-- 质量报告 / 诊断 -->
        <div v-if="terminalReport" class="mon__quality">
          <p class="mon__sec-title">质量报告</p>
          <div class="mon__quality-grid">
            <div class="mon__q-item">
              <span>行数一致性</span>
              <StatusPill
                :status="terminalReport.row_count_check === 'passed' ? 'succeeded' : 'failed'"
                :text="terminalReport.row_count_check === 'passed' ? '通过' : terminalReport.row_count_check === 'failed' ? '失败' : '待定'"
              />
            </div>
            <div v-for="(v, k) in terminalReport.error_code_distribution" :key="k" class="mon__q-item">
              <span class="mono">{{ k }}</span><span class="num">{{ v.toLocaleString() }}</span>
            </div>
          </div>
        </div>

        <div v-if="monitorRun.diagnosis" class="mon__diag">
          <p class="mon__sec-title" style="color: var(--red)">失败诊断</p>
          <p class="mon__diag-root">{{ monitorRun.diagnosis.root_cause }}</p>
          <ul class="mon__diag-list">
            <li v-for="(s, i) in monitorRun.diagnosis.suggestions" :key="i">{{ s }}</li>
          </ul>
        </div>

        <!-- 运维操作 -->
        <div class="mon__ops">
          <p class="mon__ops-note">运维操作 · 均需二次确认 + Harness 授权校验</p>
          <div class="mon__ops-btns">
            <el-button :icon="CircleClose" :disabled="isTerminal(liveStatus)" @click="doCancel">取消任务</el-button>
            <el-button :icon="RefreshLeft" :disabled="!isTerminal(liveStatus)" @click="doRerun(monitorRun)">重跑</el-button>
            <el-button type="danger" :icon="RefreshLeft" :disabled="liveStatus === 'rolled_back'" @click="doRollback">回滚</el-button>
            <el-button :icon="Delete" @click="cleanShadow">清理影子表</el-button>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CircleClose, CircleCheckFilled, Close, Delete, Lock, RefreshLeft, WarningFilled,
} from '@element-plus/icons-vue'
import type { EChartsOption } from 'echarts'
import {
  prepApi, runApi, ApiError,
  type ApprovalRequest, type ExecutionRun, type Preparation, type RoleSlot, type RunStatus,
} from '@/api'
import { useProjectStore } from '@/stores/project'
import { useAuthStore } from '@/stores/auth'
import { useRunStream } from '@/sse/useRunStream'
import GlassPanel from '@/components/GlassPanel.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusPill from '@/components/StatusPill.vue'
import RiskTag from '@/components/RiskTag.vue'
import HashChip from '@/components/HashChip.vue'
import EmptyState from '@/components/EmptyState.vue'
import VChart from '@/components/charts/VChart.vue'
import { fmtDateTime } from '@/views/studio/studioUtils'

const route = useRoute()
const projectStore = useProjectStore()
const authStore = useAuthStore()
const pid = computed(() => projectStore.currentId ?? 1)

function isTerminal(s: string) {
  return ['succeeded', 'failed', 'cancelled', 'rolled_back'].includes(s)
}

/* ================= 待我审批 ================= */
const pendingPreps = ref<Preparation[]>([])
const approvalFilter = ref<'all' | RoleSlot>('all')

const filteredPreps = computed(() => {
  if (approvalFilter.value === 'all') return pendingPreps.value
  return pendingPreps.value.filter((p) =>
    p.approval_requests.some((a) => a.required_role === approvalFilter.value && a.status === 'pending'),
  )
})

function scopeText(p: Preparation): string {
  const src = p.resource_scope?.source?.[0] ?? ''
  const tgt = p.resource_scope?.target?.[0] ?? ''
  return `${src} → ${tgt}`
}

async function loadPreps() {
  const resp = await prepApi.list(pid.value, { status: 'pending', page_size: 20 })
  pendingPreps.value = resp.items
}

/* ================= 审批对话框 ================= */
const approvalDialog = ref(false)
const activePrep = ref<Preparation | null>(null)
const deciding = ref(false)
const committing = ref(false)
const decisions = reactive<Record<'checker1' | 'checker2', 'approve' | 'reject'>>({ checker1: 'approve', checker2: 'approve' })
const comments = reactive<Record<'checker1' | 'checker2', string>>({ checker1: '', checker2: '' })
const signed = reactive<Record<'checker1' | 'checker2', boolean>>({ checker1: false, checker2: false })

/** 当前应处理的审批槽：第一个 pending 的 */
const activeSlot = computed<'checker1' | 'checker2' | null>(() => {
  const a = activePrep.value?.approval_requests.find((x) => x.status === 'pending')
  if (!a) return null
  return a.required_role === 'checker2' ? 'checker2' : 'checker1'
})

/**
 * 当前用户对 activeSlot 的审批资格预判（与服务端 D3 判定同口径）：
 * - 需持有该职责槽资格（role_slots）
 * - 禁止自批（maker_id 不能是自己）
 * - 槽间互斥（另一槽已由自己决策则不可再审）
 * 无资格时按钮置灰并提示原因；服务端仍是最终防线。
 */
const approvalDenyReason = computed<string | null>(() => {
  const p = activePrep.value
  const slot = activeSlot.value
  if (!p || !slot) return null
  if (!authStore.roleSlots.includes(slot)) return `你缺少 ${slot} 职责槽资格（D3 四眼职责分离）`
  if (p.maker_id === authStore.user?.id) return '你是本单申请人，禁止自批（D3）'
  const other = p.approval_requests.find((a) => a.required_role !== slot && a.approver_id === authStore.user?.id)
  if (other) return `你已占用 ${other.required_role} 职责槽，同单不可兼任（D3）`
  return null
})

/** 列表卡片入口的资格预判（与弹窗同口径；首个 pending 槽为准）。 */
function listDenyReason(p: Preparation): string | null {
  const pending = p.approval_requests.find((a) => a.status === 'pending')
  if (!pending) return null
  if (!authStore.roleSlots.includes(pending.required_role)) return `你缺少 ${pending.required_role} 职责槽资格（D3）`
  if (p.maker_id === authStore.user?.id) return '你是本单申请人，禁止自批（D3）'
  const other = p.approval_requests.find(
    (a) => a.required_role !== pending.required_role && a.approver_id === authStore.user?.id,
  )
  if (other) return `你已占用 ${other.required_role} 职责槽，同单不可兼任（D3）`
  return null
}

const checker1Done = computed(() => {
  const c1 = activePrep.value?.approval_requests.find((a) => a.required_role === 'checker1')
  return c1?.status === 'decided' && c1.decision === 'approve'
})

function slotRequest(slot: RoleSlot): ApprovalRequest | undefined {
  return activePrep.value?.approval_requests.find((a) => a.required_role === slot)
}

function slotStateText(slot: RoleSlot): string {
  const req = slotRequest(slot)
  if (!req) return '—'
  if (req.status === 'decided') return req.decision === 'approve' ? '已通过' : '已拒绝'
  if (slot === 'checker2' && !checker1Done.value) return '等待数据审批'
  return '当前处理'
}

function openApproval(p: Preparation, readonly = false) {
  activePrep.value = p
  decisions.checker1 = 'approve'
  decisions.checker2 = 'approve'
  comments.checker1 = ''
  comments.checker2 = ''
  signed.checker1 = readonly
  signed.checker2 = false
  approvalDialog.value = true
}

async function submitDecision() {
  const p = activePrep.value
  const slot = activeSlot.value
  if (!p || !slot) return
  const req = slotRequest(slot)
  if (!req) return
  if (!comments[slot].trim()) {
    ElMessage.warning('请填写审批意见（必填）')
    return
  }
  if (!signed[slot]) {
    ElMessage.warning('请勾选电子签名确认已核对冻结事实')
    return
  }
  deciding.value = true
  try {
    await prepApi.decide(req.id, { decision: decisions[slot], comment: comments[slot] })
    ElMessage.success(decisions[slot] === 'approve' ? '已通过该审批槽' : '已拒绝该准备单')
    // 重新拉取准备单详情刷新面板
    activePrep.value = await prepApi.get(p.id)
    await loadPreps()
    if (activePrep.value.status !== 'pending') {
      ElMessage.info(
        activePrep.value.status === 'approved'
          ? '双审批齐备，可 Commit 提交执行'
          : `准备单已${activePrep.value.status === 'rejected' ? '拒绝' : '终结'}`,
      )
    }
  } catch (err) {
    if (err instanceof ApiError && err.code === 'E_FORBIDDEN_DUTY') {
      ElMessage.error(`自批禁止：${err.message}（D3 职责互斥）`)
    } else {
      ElMessage.error(err instanceof Error ? err.message : '审批提交失败')
    }
  } finally {
    deciding.value = false
  }
}

async function doCommit() {
  const p = activePrep.value
  if (!p) return
  await ElMessageBox.confirm(
    `Commit 将校验审批与指纹一致性，签发单次 Capability 并提交正式执行。确认提交 ${p.code}？`,
    '二次确认',
    { type: 'warning', confirmButtonText: '确认 Commit', cancelButtonText: '取消' },
  )
  committing.value = true
  try {
    const resp = await prepApi.commit(p.id)
    ElMessage.success(`已签发 Capability，执行运行 RUN-${resp.execution_run_id} 已提交`)
    approvalDialog.value = false
    await Promise.all([loadPreps(), loadRuns()])
    openMonitor({ id: resp.execution_run_id } as ExecutionRun)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : 'Commit 失败')
  } finally {
    committing.value = false
  }
}

/* ================= 执行列表 ================= */
const runList = ref<ExecutionRun[]>([])
const runsLoading = ref(false)

async function loadRuns() {
  runsLoading.value = true
  try {
    const resp = await runApi.list(pid.value, { page_size: 50 })
    runList.value = resp.items
  } finally {
    runsLoading.value = false
  }
}

/* ================= 监控抽屉 ================= */
const monitorOpen = ref(false)
const monitorRun = ref<ExecutionRun | null>(null)
const focusId = ref<number | string | null>(null)
const stream = useRunStream(focusId)

const liveStatus = computed<RunStatus>(() => stream.state.status ?? monitorRun.value?.status ?? 'pending')
const liveInput = computed(() => Math.max(stream.state.input_records, monitorRun.value?.input_records ?? 0))
const liveOutput = computed(() => Math.max(stream.state.output_records, monitorRun.value?.output_records ?? 0))
const liveError = computed(() => Math.max(stream.state.error_records, monitorRun.value?.error_records ?? 0))
const liveBytes = computed(() => Math.max(stream.state.bytes_processed, monitorRun.value?.bytes_processed ?? 0))
const rejectRate = computed(() => (liveInput.value ? liveError.value / liveInput.value : 0))

const terminalReport = computed(() => {
  if (!isTerminal(liveStatus.value)) return null
  return monitorRun.value?.quality_report ?? null
})

function stageClass(s: string) {
  const cur = stream.state.sub_stage ?? monitorRun.value?.sub_stage
  if (isTerminal(liveStatus.value)) return liveStatus.value === 'succeeded' ? 'is-done' : 'is-todo'
  if (cur === s) return 'is-active'
  const order = ['COPYING', 'SPLITTING', 'SWAPPING']
  if (cur && order.indexOf(s) < order.indexOf(cur)) return 'is-done'
  return 'is-todo'
}

const rejectChartOption = computed<EChartsOption>(() => {
  const points = 24
  const base = rejectRate.value
  const data = Array.from({ length: points }, (_, i) => {
    const wave = Math.sin(i / 3) * 0.01 + (i > points - 6 ? base : base * 0.4)
    return Math.max(0, Number((wave + 0.01).toFixed(4)))
  })
  return {
    grid: { left: 44, right: 12, top: 10, bottom: 22 },
    tooltip: { trigger: 'axis', valueFormatter: (v) => `${(Number(v) * 100).toFixed(2)}%` },
    xAxis: { type: 'category', data: data.map((_, i) => `${i}`), show: false },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` } },
    series: [
      {
        type: 'line',
        smooth: true,
        data,
        showSymbol: false,
        lineStyle: { width: 2, color: '#fbbf24' },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(251,191,36,0.2)' },
              { offset: 1, color: 'rgba(251,191,36,0)' },
            ],
          },
        },
      },
    ],
  }
})

function fmtBytes(b: number): string {
  if (b >= 1_073_741_824) return `${(b / 1_073_741_824).toFixed(1)} GB`
  if (b >= 1_048_576) return `${(b / 1_048_576).toFixed(1)} MB`
  return `${(b / 1024).toFixed(0)} KB`
}

async function openMonitor(run: ExecutionRun) {
  const full = await runApi.get(run.id)
  monitorRun.value = full
  monitorOpen.value = true
  if (!isTerminal(full.status)) {
    focusId.value = full.id
  } else {
    focusId.value = null
  }
}

function closeMonitor() {
  focusId.value = null
  stream.close()
  monitorRun.value = null
  loadRuns()
}

/* ================= 运维操作 ================= */
async function doCancel() {
  const run = monitorRun.value
  if (!run) return
  await ElMessageBox.confirm(`确认取消 RUN-${run.id}？取消动作将写入审计账本。`, '二次确认', {
    type: 'warning', confirmButtonText: '确认取消', cancelButtonText: '再想想',
  })
  await runApi.cancel(run.id)
  ElMessage.success('已取消')
  monitorRun.value = await runApi.get(run.id)
}

async function doRerun(run: ExecutionRun) {
  await ElMessageBox.confirm(
    `安全重跑（R6）：将基于同一冻结指纹重新执行，生成新的 RUN。确认重跑 RUN-${run.id}？`,
    '二次确认',
    { type: 'warning', confirmButtonText: '确认重跑', cancelButtonText: '取消' },
  )
  try {
    const resp = await runApi.rerun(run.id)
    ElMessage.success(`已发起安全重跑 → RUN-${resp.execution_run_id}`)
    await loadRuns()
    openMonitor({ id: resp.execution_run_id } as ExecutionRun)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '重跑失败')
  }
}

async function doRollback() {
  const run = monitorRun.value
  if (!run) return
  await ElMessageBox.confirm(
    `受管回滚：drop_shadow + restore_state，保留现场 72h。确认回滚 RUN-${run.id}？`,
    '二次确认',
    { type: 'error', confirmButtonText: '确认回滚', cancelButtonText: '取消' },
  )
  await runApi.rollback(run.id)
  ElMessage.success('已回滚，现场保留 72h')
  monitorRun.value = await runApi.get(run.id)
}

async function cleanShadow() {
  await ElMessageBox.confirm('清理影子表 raw_orders_shadow？该操作需要 Harness 授权校验。', '二次确认', {
    type: 'warning', confirmButtonText: '确认清理', cancelButtonText: '取消',
  })
  ElMessage.success('影子表已清理（演示）')
}

onMounted(async () => {
  if (!projectStore.loaded) await projectStore.fetchList()
  await Promise.all([loadPreps(), loadRuns()])
  const focus = Number(route.query.focus)
  if (Number.isFinite(focus) && focus > 0) {
    openMonitor({ id: focus } as ExecutionRun)
  }
})
</script>

<style scoped>
.runs__sec-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.runs__sec-title { font-size: 16px; display: flex; align-items: baseline; gap: 8px; }
.runs__sec-num { color: var(--red); font-size: 14px; }
.runs__sec-hint { font-size: 12px; color: var(--txt-2); }

/* 审批卡片 */
.runs__preps { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.prep-card {
  padding: 16px 18px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--panel);
  backdrop-filter: blur(14px);
}
.prep-card__top { display: flex; align-items: center; gap: 10px; }
.prep-card__code { font-size: 12px; color: var(--txt-1); }
.prep-card__top .status-pill { margin-left: auto; }
.prep-card__title { margin: 12px 0 0; font-size: 14.5px; }
.prep-card__applicant { margin: 6px 0 0; font-size: 12px; color: var(--txt-2); }
.prep-card__scope {
  margin: 12px 0 0;
  padding: 8px 12px;
  border-radius: var(--r-sm);
  background: rgba(148, 163, 184, 0.07);
  font-size: 12px;
  color: var(--txt-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.prep-card__est { margin: 8px 0 0; font-size: 12px; color: var(--txt-2); }
.prep-card__foot { display: flex; align-items: center; justify-content: space-between; margin-top: 14px; }
.prep-card__detail { font-size: 12.5px; cursor: pointer; }

.runs__kind { font-size: 12px; color: var(--blue); }
.runs__kind.is-dry { color: var(--violet); }
.runs__substage { font-size: 12px; color: var(--cyan); }
.runs__none { color: var(--txt-2); }

/* 审批对话框 */
.apv__head { display: flex; align-items: center; gap: 10px; font-size: 16px; font-weight: 600; }
.apv { display: flex; flex-direction: column; gap: 16px; }
.apv__facts {
  padding: 14px 16px;
  border: 1px solid rgba(251, 191, 36, 0.3);
  border-radius: var(--r-md);
  background: rgba(251, 191, 36, 0.06);
}
.apv__facts-title { display: flex; align-items: center; gap: 6px; margin: 0 0 10px; font-size: 13px; color: var(--amber); }
.apv__kv { margin: 0; display: flex; flex-direction: column; gap: 8px; }
.apv__kv > div { display: grid; grid-template-columns: 88px 1fr; gap: 10px; font-size: 12.5px; }
.apv__kv dt { color: var(--txt-2); }
.apv__kv dd { margin: 0; color: var(--txt-0); }
.apv__hash { display: flex; align-items: center; gap: 10px; margin-top: 12px; }
.apv__hash-note { font-size: 11.5px; color: var(--txt-2); }

.apv__panels { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.apv__panel {
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.apv__panel.is-active { border-color: rgba(34, 211, 238, 0.45); box-shadow: var(--glow); }
.apv__panel.is-locked { opacity: 0.55; }
.apv__panel-head { display: flex; align-items: center; justify-content: space-between; font-size: 13.5px; font-weight: 600; }
.apv__panel-state { font-size: 12px; color: var(--txt-2); font-weight: 400; }
.apv__decided { display: flex; flex-direction: column; gap: 8px; }
.apv__decided-comment { margin: 0; font-size: 12.5px; color: var(--txt-1); }
.apv__cap { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 12.5px; color: var(--green); }
.apv__footer-note { float: left; font-size: 12px; color: var(--txt-2); line-height: 32px; }

/* 监控抽屉 */
.mon { display: flex; flex-direction: column; gap: 18px; }
.mon__head { display: flex; justify-content: space-between; align-items: flex-start; }
.mon__title { font-size: 17px; display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.mon__pname { font-size: 13px; color: var(--txt-1); font-weight: 400; }
.mon__meta { display: flex; align-items: center; gap: 12px; margin-top: 8px; }
.mon__kind { font-size: 12px; color: var(--txt-2); }
.mon__live { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--green); }
.mon__close { cursor: pointer; color: var(--txt-2); }
.mon__close:hover { color: var(--txt-0); }

.mon__stages { display: flex; gap: 8px; }
.mon__stage {
  flex: 1;
  text-align: center;
  padding: 8px 0;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  font-size: 12px;
  color: var(--txt-2);
}
.mon__stage.is-active {
  color: var(--cyan);
  border-color: rgba(34, 211, 238, 0.5);
  background: rgba(34, 211, 238, 0.08);
  box-shadow: var(--glow);
}
.mon__stage.is-done { color: var(--green); border-color: rgba(52, 211, 153, 0.4); background: rgba(52, 211, 153, 0.07); }

.mon__metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.mon__metric {
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: rgba(148, 163, 184, 0.05);
}
.mon__metric-label { margin: 0; font-size: 12px; color: var(--txt-2); }
.mon__metric-value { margin: 6px 0 0; font-size: 24px; font-weight: 600; }
.mon__metric-unit { font-size: 12px; color: var(--txt-2); font-weight: 400; }
.mon__metric-sub { margin: 4px 0 0; font-size: 11.5px; color: var(--txt-2); }

.mon__sec-title { margin: 0 0 10px; font-size: 13px; color: var(--txt-1); letter-spacing: 0.04em; }
.mon__super-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: var(--r-sm);
  font-size: 12.5px;
}
.mon__super-item.is-warning { color: var(--amber); background: rgba(251, 191, 36, 0.08); border: 1px solid rgba(251, 191, 36, 0.25); }
.mon__super-th { color: var(--txt-2); font-size: 12px; }

.mon__quality-grid { display: flex; flex-wrap: wrap; gap: 10px; }
.mon__q-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  font-size: 12.5px;
  color: var(--txt-1);
}

.mon__diag {
  padding: 14px 16px;
  border: 1px solid rgba(251, 113, 133, 0.3);
  border-radius: var(--r-md);
  background: rgba(251, 113, 133, 0.06);
}
.mon__diag-root { margin: 0; font-size: 13px; color: var(--txt-0); }
.mon__diag-list { margin: 10px 0 0; padding-left: 18px; font-size: 12.5px; color: var(--txt-1); }
.mon__diag-list li { padding: 2px 0; }

.mon__ops { border-top: 1px solid var(--line); padding-top: 14px; }
.mon__ops-note { margin: 0 0 10px; font-size: 12px; color: var(--txt-2); }
.mon__ops-btns { display: flex; gap: 10px; flex-wrap: wrap; }
.mon__ops-btns .el-button { margin-left: 0; }
</style>
