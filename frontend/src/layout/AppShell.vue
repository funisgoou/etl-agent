<template>
  <div class="shell">
    <div class="app-bg" />

    <!-- 顶部玻璃导航条 -->
    <header class="shell__nav glass">
      <div class="shell__brand" @click="go('dashboard')">
        <span class="shell__logo" />
        <span class="shell__wordmark grad-text">ETL·Agent</span>
      </div>

      <nav class="shell__menu">
        <router-link
          v-for="item in navItems"
          :key="item.name"
          :to="item.to"
          class="shell__link"
          :class="{ 'is-active': isActive(item.name) }"
        >
          {{ item.label }}
        </router-link>
      </nav>

      <div class="shell__right">
        <!-- 健康指示点 -->
        <el-popover placement="bottom-end" :width="260" trigger="hover">
          <template #reference>
            <span class="shell__health" :title="app.healthOk ? '全部组件正常' : '存在异常组件'">
              <span class="dot is-live" :style="{ background: app.healthOk ? 'var(--green)' : 'var(--amber)', color: app.healthOk ? 'var(--green)' : 'var(--amber)' }" />
            </span>
          </template>
          <div class="health-pop">
            <p class="health-pop__title">组件状态</p>
            <p v-for="(st, name) in app.health?.components ?? {}" :key="name" class="health-pop__row">
              <span class="mono">{{ name }}</span>
              <StatusPill :status="st === 'ok' ? 'ok' : 'degraded'" :text="st" />
            </p>
            <p v-if="!app.health" class="health-pop__row">探测中…</p>
          </div>
        </el-popover>

        <!-- 项目选择器 -->
        <el-dropdown trigger="click" @command="onProjectCommand">
          <span class="shell__project">
            {{ projectStore.current?.name ?? '选择项目' }}
            <el-icon :size="12"><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item
                v-for="p in projectStore.list"
                :key="p.id"
                :command="`switch:${p.id}`"
                :class="{ 'is-current': p.id === projectStore.currentId }"
              >
                {{ p.name }} <span class="shell__pcode mono">{{ p.code }}</span>
              </el-dropdown-item>
              <el-dropdown-item divided command="create">＋ 新建项目</el-dropdown-item>
              <el-dropdown-item command="members">成员与资格</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>

        <!-- 通知铃铛（静态演示） -->
        <el-dropdown trigger="click">
          <span class="shell__bell">
            <el-badge :value="3" :max="9">
              <el-icon :size="17"><Bell /></el-icon>
            </el-badge>
          </span>
          <template #dropdown>
            <el-dropdown-menu class="notify-menu">
              <el-dropdown-item v-for="n in notifications" :key="n">
                <span class="notify-item">{{ n }}</span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>

        <!-- 用户 -->
        <el-dropdown trigger="click" @command="onUserCommand">
          <span class="shell__user">
            <span class="shell__avatar">{{ auth.displayName.slice(0, 1) }}</span>
            <span class="shell__chip">{{ primaryRole }}</span>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>
                {{ auth.user?.display_name }}（@{{ auth.user?.username }}）
              </el-dropdown-item>
              <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <!-- 内容区 -->
    <main class="shell__main">
      <router-view v-slot="{ Component }">
        <transition name="page-fade" mode="out-in">
          <component :is="Component" :key="route.fullPath" />
        </transition>
      </router-view>
    </main>

    <!-- 新建项目弹窗 -->
    <el-dialog v-model="createVisible" title="新建项目" width="440px">
      <el-form label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="createForm.name" placeholder="如：电商数据中台" />
        </el-form-item>
        <el-form-item label="编码" required>
          <el-input v-model="createForm.code" placeholder="如：dmp" class="mono" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 成员与资格抽屉 -->
    <el-drawer v-model="memberVisible" title="成员与资格" size="480px">
      <div class="member-drawer">
        <GlassPanel title="成员列表" body-padding="12px 16px">
          <div v-for="m in members" :key="m.user_id" class="member-row">
            <span class="shell__avatar shell__avatar--sm">{{ m.display_name.slice(0, 1) }}</span>
            <span class="member-row__name">{{ m.display_name }}</span>
            <span class="mono member-row__uname">@{{ m.username }}</span>
            <StatusPill status="ok" :text="roleLabel(m.role)" />
          </div>
          <div class="member-add">
            <el-input v-model.number="memberForm.user_id" placeholder="user_id" class="mono" style="width: 110px" />
            <el-select v-model="memberForm.role" style="flex: 1">
              <el-option v-for="r in roleOptions" :key="r.value" :label="r.label" :value="r.value" />
            </el-select>
            <el-button type="primary" plain @click="addMember">添加成员</el-button>
          </div>
        </GlassPanel>

        <GlassPanel title="职责槽授权（D3：仅资格，不做互斥判定）" body-padding="12px 16px" style="margin-top: 16px">
          <div v-for="g in grants" :key="g.id" class="member-row">
            <span class="member-row__name">{{ g.display_name ?? `用户 ${g.user_id}` }}</span>
            <span class="mono member-row__slot">{{ g.role_slot }}</span>
          </div>
          <div class="member-add">
            <el-input v-model.number="grantForm.user_id" placeholder="user_id" class="mono" style="width: 110px" />
            <el-select v-model="grantForm.role_slot" style="flex: 1">
              <el-option v-for="s in slotOptions" :key="s" :label="s" :value="s" />
            </el-select>
            <el-button type="primary" plain @click="addGrant">授权</el-button>
          </div>
        </GlassPanel>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown, Bell } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { projectApi, type GlobalRole, type Member, type RoleGrant, type RoleSlot } from '@/api'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import GlassPanel from '@/components/GlassPanel.vue'
import StatusPill from '@/components/StatusPill.vue'

const route = useRoute()
const router = useRouter()
const app = useAppStore()
const auth = useAuthStore()
const projectStore = useProjectStore()

/* ---------- 导航 ---------- */

const navItems = computed(() => {
  const pid = projectStore.currentId ?? 1
  return [
    { name: 'dashboard', label: '总览工作台', to: `/p/${pid}/dashboard` },
    { name: 'connections', label: '数据资产', to: `/p/${pid}/connections` },
    { name: 'studio', label: 'Pipeline Studio', to: `/p/${pid}/studio` },
    { name: 'runs', label: '运行中心', to: `/p/${pid}/runs` },
    { name: 'governance', label: '安全治理', to: `/p/${pid}/governance` },
    { name: 'audit', label: '审计', to: `/p/${pid}/audit` },
  ]
})

function isActive(name: string) {
  if (name === 'studio') return route.name === 'studio' || route.name === 'studio-pipeline'
  return route.name === name
}

function go(name: string) {
  const item = navItems.value.find((i) => i.name === name)
  if (item) router.push(item.to)
}

// 路由中的 projectId 为真相源：同步到 store
watch(
  () => route.params.projectId,
  (pid) => {
    const id = Number(pid)
    if (Number.isFinite(id) && id > 0 && id !== projectStore.currentId) {
      projectStore.switchTo(id)
    }
  },
  { immediate: true },
)

/* ---------- 健康轮询 ---------- */

let healthTimer: ReturnType<typeof setInterval> | null = null
onMounted(async () => {
  app.refreshHealth()
  healthTimer = setInterval(() => app.refreshHealth(), 15_000)
  if (!projectStore.loaded) await projectStore.fetchList()
})
onBeforeUnmount(() => {
  if (healthTimer) clearInterval(healthTimer)
})

/* ---------- 项目选择 / 新建 ---------- */

const createVisible = ref(false)
const creating = ref(false)
const createForm = reactive({ name: '', code: '', description: '' })

function onProjectCommand(cmd: string) {
  if (cmd === 'create') {
    createVisible.value = true
    return
  }
  if (cmd === 'members') {
    openMembers()
    return
  }
  if (cmd.startsWith('switch:')) {
    const id = Number(cmd.slice(7))
    projectStore.switchTo(id)
    // 保持当前模块，仅替换项目段
    const section = String(route.name ?? 'dashboard')
    const target = section === 'studio-pipeline' ? 'studio' : section
    router.push({ name: target, params: { projectId: id } })
  }
}

async function submitCreate() {
  if (!createForm.name || !createForm.code) {
    ElMessage.warning('名称与编码必填')
    return
  }
  creating.value = true
  try {
    const p = await projectStore.createProject({ ...createForm })
    ElMessage.success(`项目「${p.name}」已创建`)
    createVisible.value = false
    createForm.name = createForm.code = createForm.description = ''
    router.push(`/p/${p.id}/dashboard`)
  } catch (e: any) {
    ElMessage.error(e?.message ?? '创建失败')
  } finally {
    creating.value = false
  }
}

/* ---------- 成员与资格抽屉 ---------- */

const memberVisible = ref(false)
const members = ref<Member[]>([])
const grants = ref<RoleGrant[]>([])
const memberForm = reactive<{ user_id: number | undefined; role: GlobalRole }>({ user_id: undefined, role: 'engineer' })
const grantForm = reactive<{ user_id: number | undefined; role_slot: RoleSlot }>({ user_id: undefined, role_slot: 'maker' })

const roleOptions: { label: string; value: GlobalRole }[] = [
  { label: 'engineer（数据工程师）', value: 'engineer' },
  { label: 'approver_data（数据审批）', value: 'approver_data' },
  { label: 'approver_security（安全审批）', value: 'approver_security' },
  { label: 'operator（运维）', value: 'operator' },
  { label: 'auditor（审计员）', value: 'auditor' },
]
const slotOptions: RoleSlot[] = ['maker', 'checker1', 'checker2', 'operator']

function roleLabel(role: string) {
  return roleOptions.find((r) => r.value === role)?.label.split('（')[0] ?? role
}

async function openMembers() {
  memberVisible.value = true
  const pid = projectStore.currentId
  if (!pid) return
  const [m, g] = await Promise.all([projectApi.listMembers(pid), projectApi.listRoleGrants(pid)])
  members.value = m
  grants.value = g
}

async function addMember() {
  const pid = projectStore.currentId
  if (!pid || !memberForm.user_id) return
  try {
    await projectApi.addMember(pid, { user_id: memberForm.user_id, role: memberForm.role })
    ElMessage.success('成员已添加')
    members.value = await projectApi.listMembers(pid)
  } catch (e: any) {
    ElMessage.error(e?.message ?? '添加失败')
  }
}

async function addGrant() {
  const pid = projectStore.currentId
  if (!pid || !grantForm.user_id) return
  try {
    await projectApi.grantRole(pid, { user_id: grantForm.user_id, role_slot: grantForm.role_slot })
    ElMessage.success('资格已授予')
    grants.value = await projectApi.listRoleGrants(pid)
  } catch (e: any) {
    ElMessage.error(e?.message ?? '授权失败')
  }
}

/* ---------- 通知 / 用户 ---------- */

const notifications = [
  'RUN-8801 进入 SPLITTING 阶段',
  'PR-018 等待 checker1 审批',
  'Benchmark #9 健康度 94 分',
]

const primaryRole = computed(() => {
  const r = auth.roles[0]
  return r ? roleLabel(r) : '访客'
})

async function onUserCommand(cmd: string) {
  if (cmd === 'logout') {
    await auth.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.shell { min-height: 100vh; }

.shell__nav {
  position: sticky;
  top: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 28px;
  height: 60px;
  padding: 0 24px;
  border-radius: 0;
  border-left: none;
  border-right: none;
  border-top: none;
}

.shell__brand { display: flex; align-items: center; gap: 10px; cursor: pointer; flex: none; }
.shell__logo {
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: var(--grad);
  box-shadow: var(--glow);
  position: relative;
}
.shell__logo::after {
  content: '';
  position: absolute;
  inset: 6px;
  border-radius: 3px;
  background: var(--bg-0);
  opacity: 0.85;
}
.shell__wordmark { font-size: 17px; font-weight: 700; letter-spacing: 0.02em; }

.shell__menu { display: flex; align-items: center; gap: 4px; flex: 1; min-width: 0; }
.shell__link {
  position: relative;
  padding: 6px 14px;
  font-size: 13.5px;
  color: var(--txt-1);
  border-radius: var(--r-sm);
  transition: color 0.22s, background 0.22s;
  white-space: nowrap;
}
.shell__link:hover { color: var(--txt-0); background: rgba(148, 163, 184, 0.08); }
.shell__link.is-active { color: var(--txt-0); }
.shell__link.is-active::after {
  content: '';
  position: absolute;
  left: 14px;
  right: 14px;
  bottom: -2px;
  height: 2px;
  border-radius: 2px;
  background: var(--grad);
  box-shadow: 0 0 12px rgba(34, 211, 238, 0.55);
}

.shell__right { display: flex; align-items: center; gap: 18px; flex: none; }
.shell__health { cursor: pointer; display: inline-flex; }
.shell__project {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--txt-0);
  font-size: 13px;
  cursor: pointer;
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: rgba(148, 163, 184, 0.06);
  transition: border-color 0.2s, box-shadow 0.2s;
}
.shell__project:hover { border-color: var(--line-strong); box-shadow: var(--glow); }
.shell__pcode { color: var(--txt-2); font-size: 11px; margin-left: 6px; }
:deep(.el-dropdown-menu__item.is-current) { color: var(--cyan); }

.shell__bell { color: var(--txt-1); cursor: pointer; display: inline-flex; }
.shell__bell:hover { color: var(--txt-0); }
.notify-item { max-width: 260px; white-space: normal; font-size: 12.5px; }

.shell__user { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; }
.shell__avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--grad);
  color: #06222b;
  font-weight: 700;
  font-size: 14px;
}
.shell__avatar--sm { width: 24px; height: 24px; font-size: 12px; flex: none; }
.shell__chip {
  font-size: 11px;
  color: var(--cyan);
  border: 1px solid rgba(34, 211, 238, 0.35);
  border-radius: 999px;
  padding: 1px 8px;
  background: rgba(34, 211, 238, 0.08);
}

.shell__main {
  max-width: 1680px;
  margin: 0 auto;
  padding: 24px;
}

.health-pop__title { margin: 0 0 8px; font-size: 13px; color: var(--txt-0); }
.health-pop__row {
  margin: 4px 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--txt-1);
}

.member-drawer { display: flex; flex-direction: column; }
.member-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--line);
}
.member-row:last-of-type { border-bottom: none; }
.member-row__name { color: var(--txt-0); font-size: 13px; }
.member-row__uname { color: var(--txt-2); font-size: 12px; flex: 1; }
.member-row__slot { color: var(--violet); font-size: 12px; margin-left: auto; }
.member-add { display: flex; gap: 8px; margin-top: 12px; }
</style>
