<template>
  <div class="conns">
    <PageHeader title="数据连接与资产管理" :subtitle="tab === 'db' ? '管理数据源连接配置与元数据探查，支持敏感字段自动脱敏' : '上传 CSV 文件并自动解析 Schema，作为文件型数据源的输入资产'" />

    <GlassPanel class="rise-in" body-padding="0">
      <el-tabs v-model="tab" class="conns__tabs">
        <el-tab-pane label="数据库连接" name="db" />
        <el-tab-pane label="文件资产" name="file" />
      </el-tabs>

      <!-- ============ 数据库连接 ============ -->
      <div v-show="tab === 'db'" class="conns__body">
        <div class="conns__toolbar">
          <el-button type="primary" :icon="Plus" @click="openCreate">新建连接</el-button>
        </div>
        <el-table :data="connList" v-loading="connLoading" class="conns__table" row-class-name="conns__row">
          <el-table-column label="连接名称" min-width="200">
            <template #default="{ row }">
              <span class="conns__name"><el-icon :size="15"><Coin /></el-icon>{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="140">
            <template #default="{ row }"><ConnTypeTag :type="row.conn_type" /></template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }"><StatusPill :status="row.status" /></template>
          </el-table-column>
          <el-table-column label="创建人" width="110">
            <template #default>张伟</template>
          </el-table-column>
          <el-table-column label="创建时间" width="170">
            <template #default="{ row }"><span class="num">{{ fmtDateTime(row.created_at) }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
              <el-button link type="primary" size="small" :loading="testingId === row.id" @click="testConn(row)">测试</el-button>
              <el-button link type="primary" size="small" @click="openProfile(row)">探查</el-button>
            </template>
          </el-table-column>
        </el-table>
        <p class="conns__foot">共 {{ connTotal }} 条连接 · hover 行高亮 · 点击「探查」展开元数据抽屉</p>
      </div>

      <!-- ============ 文件资产 ============ -->
      <div v-show="tab === 'file'" class="conns__body">
        <el-upload
          class="conns__upload"
          drag
          :show-file-list="false"
          accept=".csv"
          :http-request="doUpload"
        >
          <el-icon :size="34" class="conns__upload-icon"><UploadFilled /></el-icon>
          <p class="conns__upload-text">拖拽 CSV 文件到此处，或 <em>点击上传</em></p>
          <p class="conns__upload-hint">v1 仅支持 CSV · 上传后自动推断 Schema（D8）</p>
        </el-upload>

        <el-table :data="fileList" v-loading="fileLoading" class="conns__table">
          <el-table-column label="文件名" min-width="200">
            <template #default="{ row }">
              <span class="conns__name"><el-icon :size="15"><Document /></el-icon>{{ row.file_name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="大小" width="110">
            <template #default="{ row }"><span class="num">{{ fmtSize(row.file_size) }}</span></template>
          </el-table-column>
          <el-table-column label="格式" width="80">
            <template #default><span class="num">CSV</span></template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default><StatusPill status="parsed" text="已解析" /></template>
          </el-table-column>
          <el-table-column label="上传时间" width="170">
            <template #default="{ row }"><span class="num">{{ fmtDateTime(row.created_at) }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openSchema(row)">查看 Schema</el-button>
              <el-button link type="danger" size="small" @click="removeFile(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </GlassPanel>

    <!-- ============ 新建 / 编辑连接对话框 ============ -->
    <el-dialog v-model="connDialog" :title="editingConn ? '编辑连接' : '新建连接'" width="520px">
      <el-form label-width="88px" label-position="left">
        <el-form-item label="连接名称" required>
          <el-input v-model="connForm.name" placeholder="如 mysql_prod_orders" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="connForm.conn_type" :disabled="!!editingConn" style="width: 100%">
            <el-option v-for="t in connTypes" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="主机">
          <el-input v-model="connForm.host" placeholder="10.0.4.12" />
        </el-form-item>
        <el-form-item label="端口">
          <el-input-number v-model="connForm.port" :min="1" :max="65535" style="width: 100%" />
        </el-form-item>
        <el-form-item label="数据库">
          <el-input v-model="connForm.database" placeholder="trade" />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="connForm.username" placeholder="etl" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="connForm.password" type="password" show-password placeholder="保存后仅以掩码形式存储" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="connDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingConn" @click="saveConn">保存</el-button>
      </template>
    </el-dialog>

    <!-- ============ 元数据探查抽屉 ============ -->
    <el-drawer v-model="profileDrawer" size="460px" :with-header="false">
      <div v-if="profileConn" class="profile">
        <header class="profile__head">
          <div>
            <h3 class="profile__title">元数据探查 <span class="mono profile__conn">{{ profileConn.name }}</span></h3>
            <p class="profile__sub">
              <StatusPill :status="profileConn.status" />
              <span v-if="profile" class="profile__meta">探查耗时 2.3s · 探查时间 {{ fmtDateTime(profile.created_at) }}</span>
            </p>
          </div>
          <el-icon class="profile__close" :size="18" @click="profileDrawer = false"><Close /></el-icon>
        </header>

        <template v-if="profile">
          <section class="profile__section">
            <div class="profile__sec-head">
              <h4>Schema 结构</h4>
              <span class="num profile__rows">≈ {{ profile.stats_json.approx_rows.toLocaleString() }} 行</span>
            </div>
            <div class="profile__table-name">
              <el-icon :size="14"><Grid /></el-icon>
              <span class="mono">{{ profile.object_name }}</span>
              <span class="profile__cols-num">{{ profile.schema_json.columns.length }} 字段</span>
            </div>
            <ul class="profile__cols">
              <li v-for="col in profile.schema_json.columns" :key="col.name" class="profile__col">
                <span class="profile__col-name mono">
                  <el-icon v-if="col.is_primary_key" :size="12" color="var(--amber)"><Key /></el-icon>
                  {{ col.name }}
                  <span class="profile__col-type">{{ col.type }}</span>
                </span>
                <span class="profile__col-tags">
                  <span v-if="col.is_primary_key" class="tag tag--pk">主键</span>
                  <span v-if="col.sensitive" class="tag tag--sens">敏感</span>
                  <span v-if="col.is_incremental" class="tag tag--incr">增量字段</span>
                </span>
              </li>
            </ul>
          </section>

          <section class="profile__section">
            <div class="profile__sec-head">
              <h4>脱敏样本预览</h4>
              <span class="profile__masked-note"><el-icon :size="12"><View /></el-icon> 敏感字段已自动脱敏</span>
            </div>
            <el-table :data="profile.masked_sample_json" size="small" class="profile__sample">
              <el-table-column
                v-for="key in sampleKeys"
                :key="key"
                :prop="key"
                :label="key"
                min-width="110"
              >
                <template #default="{ row }">
                  <span class="mono" :class="{ 'profile__masked': isMasked(key, row[key]) }">{{ row[key] }}</span>
                </template>
              </el-table-column>
            </el-table>
          </section>

          <el-alert type="info" :closable="false" show-icon title="探查结果已冻结，可作为 Preparation 的 Schema 事实来源" />
        </template>

        <div v-else class="profile__empty">
          <EmptyState title="尚未探查" description="输入表名发起一次元数据探查">
            <div class="profile__probe">
              <el-input v-model="probeObject" placeholder="表名，如 orders" style="width: 200px" />
              <el-button type="primary" :loading="probing" @click="doProbe">发起探查</el-button>
            </div>
          </EmptyState>
        </div>
      </div>
    </el-drawer>

    <!-- ============ Schema 推断对话框 ============ -->
    <el-dialog v-model="schemaDialog" :title="`Schema 推断 · ${schemaFile?.file_name ?? ''}`" width="620px">
      <el-table v-if="schemaFile" :data="schemaFile.schema_json.columns" size="default">
        <el-table-column label="字段名" min-width="140">
          <template #default="{ row }"><span class="mono">{{ row.name }}</span></template>
        </el-table-column>
        <el-table-column label="推断类型" min-width="150">
          <template #default="{ row }">
            <span class="mono schema__type">{{ row.inferred_type.toUpperCase() }}</span>
            <span v-if="row.sensitive" class="tag tag--sens" style="margin-left: 6px">敏感</span>
          </template>
        </el-table-column>
        <el-table-column label="样例值" min-width="170">
          <template #default="{ row }">
            <span class="mono" :class="{ 'profile__masked': !!row.sample_masked }">{{ row.sample_masked ?? sampleOf(row) }}</span>
          </template>
        </el-table-column>
      </el-table>
      <p class="schema__note">
        <el-icon :size="13"><InfoFilled /></el-icon>
        共 {{ schemaFile?.schema_json.columns.length ?? 0 }} 个字段 · 类型由前 1,000 行采样推断 · 敏感字段展示脱敏样例
      </p>
      <template #footer>
        <el-button @click="schemaDialog = false">重新推断</el-button>
        <el-button type="primary" @click="schemaDialog = false">确认 Schema</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type UploadRequestOptions } from 'element-plus'
import { Close, Coin, Document, Grid, InfoFilled, Key, Plus, UploadFilled, View } from '@element-plus/icons-vue'
import {
  connApi,
  fileApi,
  type Connection,
  type ConnType,
  type FileAsset,
  type FileAssetColumn,
  type Profile,
} from '@/api'
import { useProjectStore } from '@/stores/project'
import GlassPanel from '@/components/GlassPanel.vue'
import PageHeader from '@/components/PageHeader.vue'
import StatusPill from '@/components/StatusPill.vue'
import EmptyState from '@/components/EmptyState.vue'
import ConnTypeTag from './ConnTypeTag.vue'
import { fmtDateTime } from '@/views/studio/studioUtils'

const projectStore = useProjectStore()
const pid = computed(() => projectStore.currentId ?? 1)

const tab = ref<'db' | 'file'>('db')

/* ---------- 连接列表 ---------- */
const connList = ref<Connection[]>([])
const connTotal = ref(0)
const connLoading = ref(false)
const testingId = ref<number | null>(null)

const connTypes: { label: string; value: ConnType }[] = [
  { label: 'MySQL', value: 'mysql' },
  { label: 'PostgreSQL', value: 'postgresql' },
  { label: 'Oracle', value: 'oracle' },
  { label: 'Doris', value: 'doris' },
  { label: 'ClickHouse', value: 'clickhouse' },
  { label: 'S3', value: 's3' },
  { label: 'REST API', value: 'rest_api' },
]

async function loadConns() {
  connLoading.value = true
  try {
    const resp = await connApi.list(pid.value, { page_size: 100 })
    connList.value = resp.items
    connTotal.value = resp.total
  } finally {
    connLoading.value = false
  }
}

async function testConn(row: Connection) {
  testingId.value = row.id
  try {
    const resp = await connApi.test(row.id)
    if (resp.ok) {
      ElMessage.success(`连接正常 · 延迟 ${resp.latency_ms}ms · 服务端 ${resp.server_version}`)
      row.status = 'connected'
    } else {
      ElMessage.error(resp.message ?? '连接失败')
      row.status = 'unreachable'
    }
  } finally {
    testingId.value = null
  }
}

/* ---------- 新建 / 编辑 ---------- */
const connDialog = ref(false)
const savingConn = ref(false)
const editingConn = ref<Connection | null>(null)
const connForm = reactive({
  name: '',
  conn_type: 'mysql' as ConnType,
  host: '',
  port: 3306,
  database: '',
  username: '',
  password: '',
})

function openCreate() {
  editingConn.value = null
  Object.assign(connForm, { name: '', conn_type: 'mysql', host: '', port: 3306, database: '', username: '', password: '' })
  connDialog.value = true
}

function openEdit(row: Connection) {
  editingConn.value = row
  const cfg = row.config_json as Record<string, unknown>
  Object.assign(connForm, {
    name: row.name,
    conn_type: row.conn_type,
    host: String(cfg.host ?? ''),
    port: Number(cfg.port ?? 3306),
    database: String(cfg.database ?? ''),
    username: String(cfg.username ?? ''),
    password: '',
  })
  connDialog.value = true
}

async function saveConn() {
  if (!connForm.name) {
    ElMessage.warning('请填写连接名称')
    return
  }
  savingConn.value = true
  try {
    const config_json: Record<string, unknown> = {
      host: connForm.host,
      port: connForm.port,
      database: connForm.database,
      username: connForm.username,
    }
    if (connForm.password) config_json.password = connForm.password
    if (editingConn.value) {
      await connApi.update(editingConn.value.id, { name: connForm.name, config_json })
      ElMessage.success('连接已更新')
    } else {
      await connApi.create(pid.value, { name: connForm.name, conn_type: connForm.conn_type, config_json })
      ElMessage.success('连接已创建')
    }
    connDialog.value = false
    await loadConns()
  } finally {
    savingConn.value = false
  }
}

/* ---------- 元数据探查 ---------- */
const profileDrawer = ref(false)
const profileConn = ref<Connection | null>(null)
const profile = ref<Profile | null>(null)
const probeObject = ref('')
const probing = ref(false)

const sampleKeys = computed(() => {
  const first = profile.value?.masked_sample_json[0]
  return first ? Object.keys(first) : []
})

function isMasked(key: string, val: unknown): boolean {
  const col = profile.value?.schema_json.columns.find((c) => c.name === key)
  return col?.sensitive === true && typeof val === 'string'
}

async function openProfile(row: Connection) {
  profileConn.value = row
  profile.value = null
  probeObject.value = row.id === 1 ? 'orders' : ''
  profileDrawer.value = true
  const resp = await connApi.listProfiles(row.id, { page_size: 1 })
  profile.value = resp.items[0] ?? null
}

async function doProbe() {
  if (!profileConn.value || !probeObject.value) return
  probing.value = true
  try {
    profile.value = await connApi.createProfile(profileConn.value.id, { object_name: probeObject.value })
    ElMessage.success('探查完成，Schema 已冻结')
  } finally {
    probing.value = false
  }
}

/* ---------- 文件资产 ---------- */
const fileList = ref<FileAsset[]>([])
const fileLoading = ref(false)
const schemaDialog = ref(false)
const schemaFile = ref<FileAsset | null>(null)

async function loadFiles() {
  fileLoading.value = true
  try {
    const resp = await fileApi.list(pid.value, { page_size: 100 })
    fileList.value = resp.items
  } finally {
    fileLoading.value = false
  }
}

function fmtSize(bytes: number): string {
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

async function doUpload(opt: UploadRequestOptions) {
  try {
    await fileApi.upload(pid.value, opt.file)
    ElMessage.success('上传成功，Schema 已自动解析')
    await loadFiles()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '上传失败')
  }
}

function openSchema(row: FileAsset) {
  schemaFile.value = row
  schemaDialog.value = true
}

function sampleOf(col: FileAssetColumn): string {
  const samples: Record<string, string> = {
    long: '88421093',
    string: 'completed',
    decimal: '129.50',
    datetime: '2026-06-01 12:33:01',
  }
  return samples[col.inferred_type] ?? '—'
}

async function removeFile(row: FileAsset) {
  await ElMessageBox.confirm(`确认删除文件资产「${row.file_name}」？该操作会写入审计账本。`, '删除确认', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await fileApi.remove(row.id)
  ElMessage.success('已删除')
  await loadFiles()
}

onMounted(async () => {
  if (!projectStore.loaded) await projectStore.fetchList()
  await Promise.all([loadConns(), loadFiles()])
})
</script>

<style scoped>
.conns__tabs { padding: 0 20px; }
.conns__tabs :deep(.el-tabs__header) { margin-bottom: 0; }
.conns__body { padding: 20px; }
.conns__toolbar { margin-bottom: 16px; }
.conns__foot { margin: 12px 0 0; font-size: 12px; color: var(--txt-2); }

.conns__name { display: inline-flex; align-items: center; gap: 8px; color: var(--txt-0); font-weight: 500; }

.conns__upload {
  margin-bottom: 18px;
}
.conns__upload :deep(.el-upload-dragger) {
  background: rgba(148, 163, 184, 0.05);
  border: 1px dashed var(--line-strong);
  border-radius: var(--r-md);
  padding: 26px 16px;
  transition: border-color 0.25s, box-shadow 0.25s;
}
.conns__upload :deep(.el-upload-dragger:hover) {
  border-color: rgba(34, 211, 238, 0.5);
  box-shadow: var(--glow);
}
.conns__upload-icon { color: var(--cyan); }
.conns__upload-text { margin: 8px 0 0; color: var(--txt-1); }
.conns__upload-text em { color: var(--cyan); font-style: normal; }
.conns__upload-hint { margin: 4px 0 0; font-size: 12px; color: var(--txt-2); }

/* ---------- 探查抽屉 ---------- */
.profile { display: flex; flex-direction: column; gap: 20px; }
.profile__head { display: flex; justify-content: space-between; align-items: flex-start; }
.profile__title { font-size: 16px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.profile__conn { color: var(--cyan); font-size: 13px; }
.profile__sub { display: flex; align-items: center; gap: 10px; margin: 8px 0 0; }
.profile__meta { font-size: 12px; color: var(--txt-2); }
.profile__close { cursor: pointer; color: var(--txt-2); }
.profile__close:hover { color: var(--txt-0); }

.profile__sec-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.profile__sec-head h4 { font-size: 14px; }
.profile__rows { font-size: 12px; color: var(--txt-1); }
.profile__table-name {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm) var(--r-sm) 0 0;
  background: rgba(148, 163, 184, 0.06);
  font-size: 13px;
}
.profile__cols-num { margin-left: auto; font-size: 12px; color: var(--txt-2); }
.profile__cols {
  margin: 0;
  padding: 0;
  list-style: none;
  border: 1px solid var(--line);
  border-top: none;
  border-radius: 0 0 var(--r-sm) var(--r-sm);
}
.profile__col {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 14px;
  border-bottom: 1px dashed var(--line);
}
.profile__col:last-child { border-bottom: none; }
.profile__col-name { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--txt-0); }
.profile__col-type { color: var(--txt-2); font-size: 12px; }
.profile__col-tags { display: flex; gap: 6px; }

.tag {
  padding: 0 7px;
  border-radius: var(--r-sm);
  font-size: 11px;
  line-height: 18px;
  border: 1px solid;
}
.tag--pk { color: var(--amber); border-color: rgba(251, 191, 36, 0.4); background: rgba(251, 191, 36, 0.1); }
.tag--sens { color: var(--red); border-color: rgba(251, 113, 133, 0.4); background: rgba(251, 113, 133, 0.1); }
.tag--incr { color: var(--blue); border-color: rgba(96, 165, 250, 0.4); background: rgba(96, 165, 250, 0.1); }

.profile__masked { color: var(--amber); }
.profile__masked-note { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--green); }
.profile__empty { padding-top: 40px; }
.profile__probe { display: flex; gap: 10px; justify-content: center; }

.schema__type { color: var(--cyan); font-size: 12.5px; }
.schema__note {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 14px 0 0;
  font-size: 12px;
  color: var(--txt-2);
}
</style>
