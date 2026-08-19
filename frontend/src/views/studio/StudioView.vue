<template>
  <div class="studio" v-loading="pageLoading">
    <template v-if="pipeline">
      <!-- 顶部：标题 + 状态横幅 -->
      <div class="studio__head rise-in">
        <div class="studio__title-wrap">
          <h2 class="studio__title">
            {{ pipeline.name }}
            <span class="mono studio__ver">{{ versionLabel(currentVersion) }}</span>
          </h2>
          <p v-if="latestPrep" class="studio__banner" :class="`is-${latestPrep.status}`">
            <span class="dot" :class="{ 'is-live': latestPrep.status === 'pending' }" />
            {{ prepBanner }}
          </p>
          <p v-else-if="designReady" class="studio__banner is-ready">
            <span class="dot" style="background: var(--green)" />
            设计已生成并通过门禁，可 Dry-Run 或提交审批
          </p>
        </div>
        <StatusPill :status="currentVersion?.status ?? 'draft'" />
      </div>

      <div class="studio__grid">
        <!-- ================= 左栏：需求对话 ================= -->
        <GlassPanel class="studio__chat rise-in" title="需求对话" subtitle="LangGraph Agent" body-padding="0">
          <div ref="chatScroll" class="chat">
            <div v-for="(m, i) in messages" :key="i" class="chat__msg" :class="`is-${m.role}`">
              <span class="chat__avatar" :class="`is-${m.role}`">
                {{ m.role === 'user' ? '张' : '' }}
                <el-icon v-if="m.role === 'agent'" :size="13"><Cpu /></el-icon>
              </span>
              <div class="chat__bubble">
                <p class="chat__text">{{ m.text }}</p>
                <span class="chat__time num">{{ m.time }}</span>
              </div>
            </div>

            <!-- 澄清问题表单（interrupt schema 驱动） -->
            <div v-if="pendingQuestion" class="chat__msg is-agent">
              <span class="chat__avatar is-agent"><el-icon :size="13"><Cpu /></el-icon></span>
              <div class="chat__bubble chat__bubble--form">
                <p class="chat__text">{{ pendingQuestion.message }}</p>
                <p class="chat__waiting"><span class="dot is-live" style="background: var(--amber)" /> 等待回答…</p>
                <div class="chat__form">
                  <div v-for="f in pendingQuestion.fields" :key="f.key" class="chat__field">
                    <label class="chat__label">{{ f.label }}<span v-if="f.required" class="chat__req">*</span></label>
                    <el-select
                      v-if="f.type === 'select'"
                      v-model="answers[f.key]"
                      :placeholder="f.placeholder"
                      size="small"
                    >
                      <el-option v-for="o in f.options ?? []" :key="o" :label="o" :value="o" />
                    </el-select>
                    <el-input
                      v-else
                      v-model="answers[f.key]"
                      :type="f.type === 'textarea' ? 'textarea' : 'text'"
                      :placeholder="f.placeholder"
                      size="small"
                    />
                  </div>
                  <el-button type="primary" size="small" :loading="answering" :icon="Promotion" @click="submitAnswers">
                    提交回答
                  </el-button>
                </div>
              </div>
            </div>

            <!-- Agent 执行进度 -->
            <div v-if="agentSteps.length" class="chat__steps">
              <p class="chat__steps-title">Agent 执行进度</p>
              <div v-for="s in agentSteps" :key="s.name" class="chat__step">
                <el-icon v-if="s.status === 'done'" :size="15" color="var(--green)"><CircleCheckFilled /></el-icon>
                <el-icon v-else-if="s.status === 'running'" :size="15" class="is-spin" color="var(--cyan)"><Loading /></el-icon>
                <el-icon v-else :size="15" color="var(--txt-2)"><CircleCheck /></el-icon>
                <span class="chat__step-name">{{ s.name }}</span>
                <span class="chat__step-detail">{{ s.detail }}</span>
              </div>
            </div>
          </div>

          <div class="chat__input">
            <el-input
              v-model="prompt"
              placeholder="描述数据搬运需求，或附加参考文件…"
              :disabled="generating"
              @keyup.enter="sendPrompt"
            />
            <el-button type="primary" :icon="Promotion" :loading="generating" circle @click="sendPrompt" />
          </div>
        </GlassPanel>

        <!-- ================= 中栏：设计审查 ================= -->
        <GlassPanel class="studio__design rise-in" body-padding="0">
          <el-tabs v-model="designTab" class="studio__tabs">
            <el-tab-pane label="设计摘要" name="summary" />
            <el-tab-pane label="HOCON配置" name="hocon" />
            <el-tab-pane label="DAG拓扑" name="dag" />
            <el-tab-pane label="字段映射" name="mapping" />
            <el-tab-pane label="质量契约" name="quality" />
          </el-tabs>

          <div v-if="!designReady" class="studio__design-empty">
            <EmptyState
              :title="generating ? 'Agent 正在生成设计…' : '尚无设计结果'"
              :description="generating ? '意图解析 → 元数据探查 → 生成配置 → 门禁校验' : '在左侧对话框描述你的数据搬运需求'"
            >
              <el-icon v-if="generating" :size="30" class="is-spin" color="var(--cyan)"><Loading /></el-icon>
            </EmptyState>
          </div>

          <template v-else-if="design?.etl_plan">
            <!-- 设计摘要 -->
            <div v-show="designTab === 'summary'" class="design">
              <div class="design__head">
                <h3 class="design__h">EtlPlan 设计摘要</h3>
                <span class="design__frozen">
                  {{ design.is_immutable ? '由 Agent 生成 · 已冻结' : '由 Agent 生成' }}
                </span>
              </div>
              <dl class="design__kv">
                <div class="design__row">
                  <dt>数据流向</dt>
                  <dd>
                    <span class="flow-chip">{{ design.etl_plan.source.connection }} · {{ design.etl_plan.source.table }}</span>
                    <el-icon :size="13"><Right /></el-icon>
                    <span class="flow-chip flow-chip--target">{{ design.etl_plan.target.connection }} · {{ design.etl_plan.target.table }}</span>
                  </dd>
                </div>
                <div class="design__row">
                  <dt>同步模式</dt>
                  <dd>{{ design.etl_plan.sync_mode }}<span v-if="design.etl_plan.incremental_field" class="design__dim"> · 增量字段 {{ design.etl_plan.incremental_field }}</span></dd>
                </div>
                <div class="design__row">
                  <dt>字段数量</dt>
                  <dd>{{ plan.mappings.length }} → {{ plan.mappings.length }}（{{ renamedCount }} 个字段改名，映射一致）</dd>
                </div>
                <div class="design__row">
                  <dt>预估数据量</dt>
                  <dd class="num">全量 ≈ {{ (design.etl_plan.estimated_full_rows ?? 0).toLocaleString() }} 行 · 日增 ≈ {{ (design.etl_plan.estimated_daily_rows ?? 0).toLocaleString() }} 行</dd>
                </div>
                <div class="design__row">
                  <dt>执行引擎</dt>
                  <dd>{{ design.etl_plan.engine }}<span class="design__dim">（哑管道全量入 raw 表，质量过滤走受管SQL）</span></dd>
                </div>
                <div class="design__row">
                  <dt>发布策略</dt>
                  <dd><span class="flow-chip flow-chip--shadow">{{ design.etl_plan.publish_strategy }}</span></dd>
                </div>
              </dl>

              <h4 class="design__sub-h">脱敏规则（{{ plan.masking_rules.length }} 条 · 强制执行）</h4>
              <ul class="design__masks">
                <li v-for="r in plan.masking_rules" :key="r.field" class="design__mask">
                  <span class="mono design__mask-field">{{ r.field }}</span>
                  <el-icon :size="12"><Right /></el-icon>
                  <span class="design__mask-rule">{{ r.description }}</span>
                  <span class="mono design__mask-sample">{{ r.sample_after }}</span>
                  <span v-if="r.enforced" class="tag-force">强制</span>
                </li>
              </ul>
            </div>

            <!-- HOCON 配置 -->
            <div v-show="designTab === 'hocon'" class="design">
              <CodeBlock :code="design.hocon ?? ''" lang="hocon" />
            </div>

            <!-- DAG 拓扑 -->
            <div v-show="designTab === 'dag'" class="design">
              <p class="design__hint">执行拓扑 · 节点可点击查看详情</p>
              <div class="dag">
                <template v-for="(n, i) in design.dag?.nodes ?? []" :key="n.id">
                  <button
                    class="dag__node"
                    :class="{ 'is-active': activeDagNode?.id === n.id }"
                    type="button"
                    @click="activeDagNode = n"
                  >
                    <span class="dag__kind" :data-kind="n.kind" />
                    <span class="dag__label">{{ n.label }}</span>
                    <span class="dag__sub">{{ n.sub }}</span>
                  </button>
                  <el-icon v-if="i < (design.dag?.nodes.length ?? 0) - 1" :size="16" class="dag__arrow"><Right /></el-icon>
                </template>
              </div>
              <el-alert
                v-if="activeDagNode"
                type="info"
                :closable="false"
                show-icon
                class="dag__detail"
                :title="`已选中「${activeDagNode.label}」：${activeDagNode.detail ?? activeDagNode.sub ?? ''}`"
              />
            </div>

            <!-- 字段映射 -->
            <div v-show="designTab === 'mapping'" class="design">
              <div class="design__head">
                <h3 class="design__h">字段映射 · 源 {{ plan.mappings.length }} 字段 → 目标 {{ plan.mappings.length }} 字段</h3>
                <span class="design__renamed-note">{{ renamedCount }} 处改名 · 黄色高亮</span>
              </div>
              <el-table :data="plan.mappings" size="default" :row-class-name="mappingRowClass">
                <el-table-column label="源字段 (MySQL)" min-width="150">
                  <template #default="{ row }"><span class="mono">{{ row.source_field }}</span><span class="design__col-type"> {{ row.source_type }}</span></template>
                </el-table-column>
                <el-table-column label="映射" width="70" align="center">
                  <template #default><el-icon :size="13" color="var(--txt-2)"><Right /></el-icon></template>
                </el-table-column>
                <el-table-column label="目标字段 (Doris)" min-width="150">
                  <template #default="{ row }">
                    <span class="mono" :style="row.renamed ? 'color: var(--amber)' : ''">{{ row.target_field }}</span>
                    <span class="design__col-type"> {{ row.target_type }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="说明" min-width="140">
                  <template #default="{ row }"><span class="design__col-comment">{{ row.comment ?? '' }}</span></template>
                </el-table-column>
              </el-table>

              <div class="design__head" style="margin-top: 22px">
                <h3 class="design__h">脱敏前后样本对比</h3>
                <span class="design__dim">仅展示样本 · 非真实数据</span>
              </div>
              <el-table :data="plan.masking_rules" size="default">
                <el-table-column label="字段" width="110">
                  <template #default="{ row }"><span class="mono">{{ row.field }}</span></template>
                </el-table-column>
                <el-table-column label="脱敏前" min-width="180">
                  <template #default="{ row }"><span class="mono">{{ row.sample_before }}</span></template>
                </el-table-column>
                <el-table-column label="脱敏后" min-width="180">
                  <template #default="{ row }">
                    <span class="mono" style="color: var(--green)"><el-icon :size="12"><CircleCheckFilled /></el-icon> {{ row.sample_after }}</span>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <!-- 质量契约 -->
            <div v-show="designTab === 'quality'" class="design">
              <div class="design__head">
                <h3 class="design__h">质量契约 · {{ plan.quality_contract.rules.length }} 条受管规则</h3>
                <span class="design__dim">由 Harness 沙箱执行 · 不匹配即判失败</span>
              </div>
              <el-table :data="plan.quality_contract.rules" size="default">
                <el-table-column label="规则码" width="150">
                  <template #default="{ row }"><span class="mono" style="color: var(--violet)">{{ row.code }}</span></template>
                </el-table-column>
                <el-table-column label="字段" width="110">
                  <template #default="{ row }"><span class="mono">{{ row.field ?? '—' }}</span></template>
                </el-table-column>
                <el-table-column label="表达式" min-width="200">
                  <template #default="{ row }"><span class="mono">{{ row.expression }}</span></template>
                </el-table-column>
                <el-table-column label="级别" width="90">
                  <template #default="{ row }">
                    <span class="tag-sev" :class="row.severity === 'blocking' ? 'is-blocking' : 'is-warning'">
                      {{ row.severity === 'blocking' ? '阻断' : '警告' }}
                    </span>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </template>

          <!-- 底部：门禁条 + 操作 -->
          <div class="studio__gate">
            <div class="studio__gate-info" :class="{ 'is-pass': design?.gate_report?.passed }">
              <el-icon v-if="design?.gate_report?.passed" :size="16" color="var(--green)"><CircleCheckFilled /></el-icon>
              <el-icon v-else :size="16" color="var(--txt-2)"><CircleCheck /></el-icon>
              <span v-if="design?.gate_report">
                门禁校验{{ design.gate_report.passed ? '全部通过' : '未通过' }}
                （{{ design.gate_report.passed_count }}/{{ design.gate_report.total }} 项）
              </span>
              <span v-else>门禁校验待执行</span>
              <el-popover v-if="design?.gate_report" placement="top" :width="320" trigger="click">
                <template #reference><a class="studio__gate-link">查看报告 ›</a></template>
                <ul class="gate-list">
                  <li v-for="f in design.gate_report.findings" :key="f.code">
                    <el-icon :size="13" :color="f.status === 'passed' ? 'var(--green)' : 'var(--red)'"><CircleCheckFilled /></el-icon>
                    {{ f.name }} <span class="mono gate-list__code">{{ f.code }}</span>
                  </li>
                </ul>
              </el-popover>
            </div>
            <div class="studio__gate-actions">
              <span class="studio__gate-note">提交后将冻结 Preparation 并进入四眼审批流</span>
              <el-button :disabled="!designReady" :loading="dryRunning" @click="doDryRun">
                <el-icon style="margin-right: 4px"><VideoPlay /></el-icon>Dry-Run 试运行
              </el-button>
              <el-button type="primary" :disabled="!designReady || !!latestPrep" :loading="submitting" @click="submitApproval">
                <el-icon style="margin-right: 4px"><Stamp /></el-icon>提交审批
              </el-button>
            </div>
          </div>
        </GlassPanel>

        <!-- ================= 右栏：版本与审批 ================= -->
        <div class="studio__side">
          <GlassPanel class="rise-in" title="当前版本" body-padding="16px">
            <dl class="side-kv">
              <div><dt>版本号</dt><dd class="mono">{{ versionLabel(currentVersion) }}</dd></div>
              <div>
                <dt>SHA256</dt>
                <dd><HashChip v-if="currentVersion?.artifact_digest" :hash="currentVersion.artifact_digest" :head="6" :tail="4" /><span v-else class="side-kv__none">未冻结</span></dd>
              </div>
              <div><dt>创建时间</dt><dd class="num">{{ fmtDateTime(currentVersion?.created_at) }}</dd></div>
              <div><dt>状态</dt><dd><StatusPill :status="currentVersion?.status ?? 'draft'" /></dd></div>
            </dl>
          </GlassPanel>

          <GlassPanel class="rise-in" title="三阶段审批流" body-padding="16px">
            <div class="flow">
              <div v-for="step in approvalFlow" :key="step.name" class="flow__step">
                <span class="flow__dot" :class="`is-${step.state}`">
                  <el-icon v-if="step.state === 'done'" :size="11"><Check /></el-icon>
                </span>
                <div class="flow__body">
                  <p class="flow__name">{{ step.name }}<span class="flow__state" :class="`is-${step.state}`">{{ step.stateText }}</span></p>
                  <p class="flow__desc">{{ step.desc }}</p>
                </div>
              </div>
            </div>
          </GlassPanel>

          <GlassPanel v-if="latestPrep" class="rise-in" title="风险等级" body-padding="16px">
            <div class="risk">
              <RiskTag :level="latestPrep.risk_level" />
              <p class="risk__desc">{{ riskDesc }}</p>
            </div>
          </GlassPanel>

          <GlassPanel class="rise-in" title="操作历史" body-padding="8px 16px">
            <ul class="history">
              <li v-for="h in history" :key="h.id" class="history__item">
                <span class="history__text">{{ h.actor_name }} · {{ h.summary }}</span>
                <span class="history__time num">{{ fmtTime(h.created_at) }}</span>
              </li>
              <li v-if="!history.length" class="history__empty">暂无操作记录</li>
            </ul>
          </GlassPanel>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Check, CircleCheck, CircleCheckFilled, Cpu, Loading, Promotion, Right, Stamp, VideoPlay,
} from '@element-plus/icons-vue'
import {
  auditApi, genApi, pipelineApi, prepApi,
  type AgentRunStep, type AuditEvent, type DagNode, type DesignResult,
  type PendingQuestion, type PipelineDetail, type PipelineVersion, type Preparation,
} from '@/api'
import GlassPanel from '@/components/GlassPanel.vue'
import StatusPill from '@/components/StatusPill.vue'
import RiskTag from '@/components/RiskTag.vue'
import HashChip from '@/components/HashChip.vue'
import CodeBlock from '@/components/CodeBlock.vue'
import EmptyState from '@/components/EmptyState.vue'
import { fmtDateTime, fmtTime, nowTime, versionLabel } from './studioUtils'

const route = useRoute()
const router = useRouter()

const pageLoading = ref(true)
const pipeline = ref<PipelineDetail | null>(null)
const currentVersion = ref<PipelineVersion | null>(null)
const design = ref<DesignResult | null>(null)
const preps = ref<Preparation[]>([])
const history = ref<AuditEvent[]>([])

/* ---------- 对话状态 ---------- */
interface ChatMsg { role: 'user' | 'agent'; text: string; time: string }
const messages = ref<ChatMsg[]>([])
const prompt = ref('')
const generating = ref(false)
const answering = ref(false)
const agentRunId = ref<number | null>(null)
const pendingQuestion = ref<PendingQuestion | null>(null)
const answers = reactive<Record<string, string>>({})
const agentSteps = ref<AgentRunStep[]>([])
const chatScroll = ref<HTMLDivElement>()

/* ---------- 设计展示状态 ---------- */
const designTab = ref('summary')
const activeDagNode = ref<DagNode | null>(null)
const dryRunning = ref(false)
const submitting = ref(false)

let pollTimer: ReturnType<typeof setInterval> | null = null

const plan = computed(() => design.value?.etl_plan ?? { mappings: [], masking_rules: [], quality_contract: { rules: [] } })
const renamedCount = computed(() => (plan.value.mappings ?? []).filter((m) => m.renamed).length)
const designReady = computed(() => (design.value?.etl_plan?.mappings?.length ?? 0) > 0)

const latestPrep = computed(() =>
  preps.value
    .filter((p) => p.version_id === currentVersion.value?.id)
    .sort((a, b) => b.id - a.id)[0] ?? null,
)

const prepBanner = computed(() => {
  const p = latestPrep.value
  if (!p) return ''
  const map: Record<string, string> = {
    pending: `审批中 · Preparation #${p.code} 已冻结，等待${p.approval_requests.find((a) => a.status === 'pending')?.required_role === 'checker2' ? '安全' : '数据'}审批`,
    approved: `审批通过 · ${p.code} 可 Commit 提交执行`,
    rejected: `已拒绝 · ${p.code}，请修改后重新提交`,
    committed: `已提交执行 · ${p.code}`,
    expired: `已过期 · ${p.code}`,
    cancelled: `已取消 · ${p.code}`,
  }
  return map[p.status] ?? p.status
})

/* ---------- 三阶段审批流 ---------- */
const approvalFlow = computed(() => {
  const p = latestPrep.value
  const c1 = p?.approval_requests.find((a) => a.required_role === 'checker1')
  const c2 = p?.approval_requests.find((a) => a.required_role === 'checker2')
  const stateOf = (a?: typeof c1): 'done' | 'active' | 'todo' => {
    if (!a) return 'todo'
    if (a.status === 'decided') return a.decision === 'approve' ? 'done' : 'todo'
    return 'active'
  }
  return [
    {
      name: 'Prepare',
      state: p ? 'done' : 'todo',
      stateText: p ? '已完成' : '待生成',
      desc: p ? `${p.maker_name} · 冻结准备单 ${p.code}` : '冻结版本并生成准备单',
    },
    {
      name: 'Checker1 · 数据审批',
      state: stateOf(c1),
      stateText: c1?.status === 'decided' ? (c1.decision === 'approve' ? '已通过' : '已拒绝') : c1 ? '进行中' : '待处理',
      desc: c1?.status === 'decided' ? `${c1.approver_name}：${c1.comment || '—'}` : '等待 李娜 处理',
    },
    {
      name: 'Checker2 · 安全审批',
      state: stateOf(c2),
      stateText: c2?.status === 'decided' ? (c2.decision === 'approve' ? '已通过' : '已拒绝') : '待处理',
      desc: '数据审批通过后开放',
    },
    {
      name: 'Commit',
      state: p?.status === 'committed' ? 'done' : 'todo',
      stateText: p?.status === 'committed' ? '已提交' : '待处理',
      desc: '双审批通过后签发安全令牌',
    },
  ] as const
})

const riskDesc = computed(() => {
  const map: Record<string, string> = {
    P0: '极高风险 · 涉敏财务/核心域，需数据+安全双审批，预算硬熔断',
    P1: '中风险 · 涉及 email/phone 敏感字段脱敏，需数据+安全双审批；预算上限 300 credits，超时 30min 自动熔断',
    P2: '低风险 · 常规同步，双审批从简',
    P3: '极低风险 · 只读探查类操作',
  }
  return map[latestPrep.value?.risk_level ?? 'P3']
})

/* ---------- 数据加载 ---------- */
async function loadAll() {
  const pid = Number(route.params.pipelineId)
  pipeline.value = await pipelineApi.get(pid)
  currentVersion.value =
    pipeline.value.versions.find((v) => v.id === pipeline.value?.latest_version_id) ??
    pipeline.value.versions.sort((a, b) => b.id - a.id)[0] ??
    null
  if (currentVersion.value) {
    design.value = await genApi.getDesign(currentVersion.value.id)
    if (designReady.value) {
      activeDagNode.value = design.value?.dag?.nodes[2] ?? design.value?.dag?.nodes[0] ?? null
    }
  }
  const [prepPage, auditPage] = await Promise.all([
    prepApi.list(route.params.projectId as string, { page_size: 50 }),
    auditApi.events({ project_id: route.params.projectId as string, page_size: 6 }),
  ])
  preps.value = prepPage.items
  history.value = auditPage.items
}

/* ---------- 对话 → 生成 ---------- */
async function sendPrompt() {
  const text = prompt.value.trim()
  if (!text || !currentVersion.value || generating.value) return
  messages.value.push({ role: 'user', text, time: nowTime() })
  prompt.value = ''
  generating.value = true
  pendingQuestion.value = null
  try {
    const resp = await genApi.trigger(currentVersion.value.id, text)
    agentRunId.value = resp.run_id
    scrollChat()
    startPoll()
  } catch (err) {
    generating.value = false
    ElMessage.error(err instanceof Error ? err.message : '触发生成失败')
  }
}

function startPoll() {
  stopPoll()
  pollTimer = setInterval(pollAgentRun, 900)
}

function stopPoll() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

async function pollAgentRun() {
  if (agentRunId.value == null) return
  const run = await genApi.getRun(agentRunId.value)
  agentSteps.value = run.steps ?? []
  if (run.status === 'waiting_input' && run.pending_question) {
    pendingQuestion.value = run.pending_question
    for (const f of run.pending_question.fields) {
      if (!(f.key in answers)) answers[f.key] = f.value ?? ''
    }
    stopPoll()
    generating.value = false
    messages.value.push({ role: 'agent', text: run.pending_question.message, time: nowTime() })
    scrollChat()
  } else if (run.status === 'succeeded') {
    stopPoll()
    generating.value = false
    pendingQuestion.value = null
    messages.value.push({ role: 'agent', text: '设计已生成并通过 6 项门禁校验，请在右侧审查 EtlPlan / HOCON / 字段映射，确认后可 Dry-Run 或提交审批。', time: nowTime() })
    if (currentVersion.value) {
      design.value = await genApi.getDesign(currentVersion.value.id)
      activeDagNode.value = design.value?.dag?.nodes[2] ?? null
      const p = await pipelineApi.get(Number(route.params.pipelineId))
      pipeline.value = p
      currentVersion.value = p.versions.find((v) => v.id === currentVersion.value?.id) ?? currentVersion.value
    }
    scrollChat()
  } else if (run.status === 'failed') {
    stopPoll()
    generating.value = false
    ElMessage.error('生成失败，请调整需求描述后重试')
  }
  scrollChat()
}

async function submitAnswers() {
  if (agentRunId.value == null) return
  const missing = pendingQuestion.value?.fields.filter((f) => f.required && !answers[f.key]?.trim())
  if (missing?.length) {
    ElMessage.warning(`请填写：${missing.map((f) => f.label).join('、')}`)
    return
  }
  answering.value = true
  try {
    await genApi.answer(agentRunId.value, { ...answers })
    pendingQuestion.value = null
    generating.value = true
    messages.value.push({
      role: 'user',
      text: Object.entries(answers).map(([k, v]) => `${k}: ${v}`).join('；'),
      time: nowTime(),
    })
    startPoll()
  } finally {
    answering.value = false
  }
}

function scrollChat() {
  nextTick(() => {
    if (chatScroll.value) chatScroll.value.scrollTop = chatScroll.value.scrollHeight
  })
}

/* ---------- 操作 ---------- */
async function doDryRun() {
  if (!currentVersion.value) return
  dryRunning.value = true
  try {
    if (currentVersion.value.status !== 'frozen') {
      const fr = await genApi.freeze(currentVersion.value.id)
      currentVersion.value = { ...currentVersion.value, status: 'frozen', artifact_digest: fr.artifact_digest }
    }
    const resp = await genApi.dryRun(currentVersion.value.id)
    ElMessage.success(`Dry-Run 已发起（RUN-${resp.execution_run_id}），前往运行中心查看实时进度`)
    router.push(`/p/${route.params.projectId}/runs?focus=${resp.execution_run_id}`)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : 'Dry-Run 发起失败')
  } finally {
    dryRunning.value = false
  }
}

async function submitApproval() {
  if (!currentVersion.value) return
  submitting.value = true
  try {
    if (currentVersion.value.status !== 'frozen') {
      const fr = await genApi.freeze(currentVersion.value.id)
      currentVersion.value = { ...currentVersion.value, status: 'frozen', artifact_digest: fr.artifact_digest }
    }
    const prep = await prepApi.create(currentVersion.value.id)
    preps.value.unshift(prep)
    ElMessage.success(`准备单 ${prep.code} 已冻结并进入四眼审批流`)
    const auditPage = await auditApi.events({ project_id: route.params.projectId as string, page_size: 6 })
    history.value = auditPage.items
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '提交审批失败')
  } finally {
    submitting.value = false
  }
}

function mappingRowClass({ row }: { row: { renamed?: boolean } }) {
  return row.renamed ? 'mapping-row--renamed' : ''
}

onMounted(async () => {
  try {
    await loadAll()
  } finally {
    pageLoading.value = false
  }
})

onBeforeUnmount(stopPoll)
</script>

<style scoped>
.studio__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.studio__title { font-size: 20px; display: flex; align-items: baseline; gap: 10px; }
.studio__ver { font-size: 13px; color: var(--cyan); }
.studio__banner {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 6px 0 0;
  font-size: 12.5px;
  color: var(--amber);
}
.studio__banner .dot { background: var(--amber); }
.studio__banner.is-approved .dot, .studio__banner.is-ready .dot { background: var(--green); }
.studio__banner.is-approved, .studio__banner.is-ready { color: var(--green); }
.studio__banner.is-rejected { color: var(--red); }
.studio__banner.is-rejected .dot { background: var(--red); }

.studio__grid {
  display: grid;
  grid-template-columns: 330px minmax(0, 1fr) 300px;
  gap: 16px;
  align-items: start;
}

/* ---------- 对话 ---------- */
.studio__chat { display: flex; flex-direction: column; height: calc(100vh - 210px); min-height: 520px; }
.chat {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.chat__msg { display: flex; gap: 10px; align-items: flex-start; }
.chat__msg.is-user { flex-direction: row-reverse; }
.chat__avatar {
  width: 28px;
  height: 28px;
  flex: none;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 12px;
  color: #fff;
}
.chat__avatar.is-user { background: linear-gradient(135deg, #60a5fa, #818cf8); }
.chat__avatar.is-agent { background: var(--grad); }
.chat__bubble {
  max-width: 88%;
  padding: 10px 12px;
  border-radius: var(--r-md);
  background: rgba(148, 163, 184, 0.08);
  border: 1px solid var(--line);
}
.chat__msg.is-user .chat__bubble {
  background: rgba(96, 165, 250, 0.14);
  border-color: rgba(96, 165, 250, 0.3);
}
.chat__bubble--form { max-width: 100%; width: 100%; }
.chat__text { margin: 0; font-size: 13px; white-space: pre-wrap; color: var(--txt-0); }
.chat__time { display: block; margin-top: 4px; font-size: 11px; color: var(--txt-2); }
.chat__waiting { display: flex; align-items: center; gap: 6px; margin: 8px 0 0; font-size: 12px; color: var(--amber); }
.chat__form {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--line);
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: flex-start;
}
.chat__field { width: 100%; }
.chat__field .el-input, .chat__field .el-select { width: 100%; }
.chat__label { display: block; font-size: 12px; color: var(--txt-1); margin-bottom: 4px; }
.chat__req { color: var(--red); margin-left: 2px; }

.chat__steps {
  margin-top: 4px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: rgba(148, 163, 184, 0.05);
}
.chat__steps-title { margin: 0 0 10px; font-size: 12px; color: var(--txt-2); letter-spacing: 0.06em; }
.chat__step { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 12.5px; }
.chat__step-name { color: var(--txt-0); flex: none; }
.chat__step-detail { color: var(--txt-2); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.chat__input {
  display: flex;
  gap: 10px;
  padding: 12px 16px;
  border-top: 1px solid var(--line);
}
.is-spin { animation: spin 1.2s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ---------- 设计中栏 ---------- */
.studio__design { min-height: calc(100vh - 210px); display: flex; flex-direction: column; }
.studio__tabs { padding: 0 20px; }
.studio__design-empty { padding: 40px 0; flex: 1; }
.design { padding: 18px 20px; flex: 1; }
.design__head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.design__h { font-size: 15px; }
.design__sub-h { margin: 22px 0 12px; font-size: 13.5px; color: var(--txt-0); }
.design__frozen { font-size: 12px; color: var(--txt-2); }
.design__dim { font-size: 12px; color: var(--txt-2); }
.design__hint { margin: 0 0 14px; font-size: 12.5px; color: var(--txt-2); }
.design__renamed-note { font-size: 12px; color: var(--amber); }

.design__kv { margin: 0; display: flex; flex-direction: column; }
.design__row {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 12px;
  padding: 9px 0;
  border-bottom: 1px dashed var(--line);
  font-size: 13px;
}
.design__row dt { color: var(--txt-2); }
.design__row dd { margin: 0; color: var(--txt-0); display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.flow-chip {
  padding: 2px 10px;
  border-radius: var(--r-sm);
  border: 1px solid rgba(34, 211, 238, 0.35);
  background: rgba(34, 211, 238, 0.08);
  color: var(--cyan);
  font-size: 12px;
}
.flow-chip--target { border-color: rgba(167, 139, 250, 0.35); background: rgba(167, 139, 250, 0.08); color: var(--violet); }
.flow-chip--shadow { border-color: rgba(96, 165, 250, 0.35); background: rgba(96, 165, 250, 0.08); color: var(--blue); }

.design__masks { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 8px; }
.design__mask {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: rgba(148, 163, 184, 0.05);
  font-size: 13px;
}
.design__mask-field { color: var(--txt-0); }
.design__mask-rule { color: var(--txt-1); }
.design__mask-sample { color: var(--amber); font-size: 12px; }
.tag-force {
  margin-left: auto;
  padding: 0 8px;
  border-radius: var(--r-sm);
  font-size: 11px;
  line-height: 18px;
  color: var(--red);
  border: 1px solid rgba(251, 113, 133, 0.4);
  background: rgba(251, 113, 133, 0.1);
}

/* DAG */
.dag { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 16px; }
.dag__node {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  padding: 12px 16px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: rgba(148, 163, 184, 0.06);
  color: inherit;
  font: inherit;
  cursor: pointer;
  transition: border-color 0.22s, box-shadow 0.22s, transform 0.22s;
}
.dag__node:hover { transform: translateY(-2px); border-color: var(--line-strong); }
.dag__node.is-active {
  border-color: rgba(34, 211, 238, 0.55);
  box-shadow: var(--glow);
}
.dag__kind { width: 100%; height: 3px; border-radius: 2px; background: var(--grad); margin-bottom: 4px; }
.dag__label { font-size: 13px; color: var(--txt-0); }
.dag__sub { font-size: 11.5px; color: var(--txt-2); }
.dag__arrow { color: var(--txt-2); flex: none; }
.dag__detail { max-width: 640px; }

.design__col-type { color: var(--txt-2); font-size: 12px; }
.design__col-comment { font-size: 12.5px; color: var(--txt-1); }
.tag-sev { padding: 1px 8px; border-radius: var(--r-sm); font-size: 11.5px; border: 1px solid; }
.tag-sev.is-blocking { color: var(--red); border-color: rgba(251, 113, 133, 0.4); background: rgba(251, 113, 133, 0.1); }
.tag-sev.is-warning { color: var(--amber); border-color: rgba(251, 191, 36, 0.4); background: rgba(251, 191, 36, 0.1); }

:deep(.mapping-row--renamed) { background: rgba(251, 191, 36, 0.07) !important; }

/* 底部审批条 */
.studio__gate {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 20px;
  border-top: 1px solid var(--line);
  flex-wrap: wrap;
}
.studio__gate-info { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--txt-1); }
.studio__gate-info.is-pass { color: var(--green); }
.studio__gate-link { font-size: 12px; cursor: pointer; }
.studio__gate-actions { display: flex; align-items: center; gap: 10px; }
.studio__gate-note { font-size: 12px; color: var(--txt-2); }

.gate-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 8px; }
.gate-list li { display: flex; align-items: center; gap: 8px; font-size: 12.5px; }
.gate-list__code { color: var(--txt-2); font-size: 11px; }

/* ---------- 右栏 ---------- */
.studio__side { display: flex; flex-direction: column; gap: 16px; }
.side-kv { margin: 0; display: flex; flex-direction: column; gap: 10px; }
.side-kv > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 12.5px; }
.side-kv dt { color: var(--txt-2); }
.side-kv dd { margin: 0; color: var(--txt-0); }
.side-kv__none { color: var(--txt-2); font-size: 12px; }

.flow { display: flex; flex-direction: column; }
.flow__step { display: flex; gap: 12px; position: relative; padding-bottom: 16px; }
.flow__step:last-child { padding-bottom: 0; }
.flow__step:not(:last-child)::before {
  content: '';
  position: absolute;
  left: 7px;
  top: 18px;
  bottom: 0;
  width: 1px;
  background: var(--line-strong);
}
.flow__dot {
  width: 15px;
  height: 15px;
  flex: none;
  border-radius: 50%;
  display: grid;
  place-items: center;
  margin-top: 3px;
  border: 1px solid var(--line-strong);
  color: #fff;
  z-index: 1;
}
.flow__dot.is-done { background: var(--green); border-color: var(--green); }
.flow__dot.is-active { background: var(--blue); border-color: var(--blue); box-shadow: 0 0 10px rgba(96, 165, 250, 0.5); }
.flow__dot.is-todo { background: transparent; }
.flow__name { margin: 0; font-size: 13px; color: var(--txt-0); display: flex; align-items: center; gap: 8px; }
.flow__state { font-size: 11px; }
.flow__state.is-done { color: var(--green); }
.flow__state.is-active { color: var(--blue); }
.flow__state.is-todo { color: var(--txt-2); }
.flow__desc { margin: 2px 0 0; font-size: 12px; color: var(--txt-2); }

.risk { display: flex; flex-direction: column; gap: 10px; }
.risk__desc { margin: 0; font-size: 12.5px; color: var(--txt-1); line-height: 1.7; }

.history { margin: 0; padding: 0; list-style: none; }
.history__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px dashed var(--line);
  font-size: 12.5px;
}
.history__item:last-child { border-bottom: none; }
.history__text { color: var(--txt-1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history__time { color: var(--txt-2); font-size: 12px; flex: none; }
.history__empty { padding: 16px 0; text-align: center; color: var(--txt-2); font-size: 12.5px; }

@media (max-width: 1280px) {
  .studio__grid { grid-template-columns: 300px minmax(0, 1fr); }
  .studio__side { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(2, 1fr); }
}
</style>
