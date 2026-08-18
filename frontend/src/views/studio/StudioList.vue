<template>
  <div class="studio-list">
    <PageHeader title="Pipeline Studio" subtitle="用自然语言描述数据搬运需求，Agent 生成可审计的 ETL 配置">
      <template #actions>
        <el-button type="primary" :icon="Plus" @click="createDialog = true">新建 Pipeline</el-button>
      </template>
    </PageHeader>

    <div v-loading="loading" class="studio-list__grid">
      <div
        v-for="p in pipelines"
        :key="p.id"
        class="pl-card hover-lift rise-in"
        @click="open(p.id)"
      >
        <div class="pl-card__head">
          <span class="pl-card__icon"><el-icon :size="18"><Connection /></el-icon></span>
          <StatusPill :status="p.status === 'active' ? 'executed' : 'draft'" :text="p.status === 'active' ? '运行中' : '草稿'" />
        </div>
        <h3 class="pl-card__name">{{ p.name }}</h3>
        <p class="pl-card__desc">{{ p.description || '暂无描述' }}</p>
        <div class="pl-card__foot">
          <span class="mono pl-card__code">{{ p.code }}</span>
          <span class="pl-card__date num">{{ fmtDate(p.created_at) }}</span>
        </div>
      </div>

      <!-- 新建占位卡 -->
      <button class="pl-card pl-card--new" type="button" @click="createDialog = true">
        <el-icon :size="26"><Plus /></el-icon>
        <span>新建 Pipeline</span>
        <span class="pl-card__new-hint">从一句需求开始</span>
      </button>
    </div>

    <EmptyState v-if="!loading && !pipelines.length" title="暂无 Pipeline" description="点击右上角新建，从一句自然语言需求开始" />

    <el-dialog v-model="createDialog" title="新建 Pipeline" width="480px">
      <el-form label-width="80px" label-position="left">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="如 orders 每日增量同步" />
        </el-form-item>
        <el-form-item label="编码" required>
          <el-input v-model="form.code" placeholder="如 orders_dwd（唯一标识）" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="数据来源、去向、同步模式…" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="create">创建并进入 Studio</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Connection, Plus } from '@element-plus/icons-vue'
import { pipelineApi, type Pipeline } from '@/api'
import { useProjectStore } from '@/stores/project'
import PageHeader from '@/components/PageHeader.vue'
import StatusPill from '@/components/StatusPill.vue'
import EmptyState from '@/components/EmptyState.vue'
import { fmtDate } from './studioUtils'

const router = useRouter()
const projectStore = useProjectStore()
const pid = computed(() => projectStore.currentId ?? 1)

const pipelines = ref<Pipeline[]>([])
const loading = ref(false)
const createDialog = ref(false)
const creating = ref(false)
const form = reactive({ name: '', code: '', description: '' })

function open(id: number) {
  router.push(`/p/${pid.value}/studio/pipeline/${id}`)
}

async function create() {
  if (!form.name || !form.code) {
    ElMessage.warning('请填写名称与编码')
    return
  }
  creating.value = true
  try {
    const p = await pipelineApi.create({ project_id: pid.value, ...form })
    ElMessage.success('已创建，进入 Studio')
    createDialog.value = false
    open(p.id)
  } finally {
    creating.value = false
  }
}

onMounted(async () => {
  if (!projectStore.loaded) await projectStore.fetchList()
  loading.value = true
  try {
    const resp = await pipelineApi.list(pid.value, { page_size: 100 })
    pipelines.value = resp.items
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.studio-list__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.pl-card {
  padding: 18px 20px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--panel);
  backdrop-filter: blur(14px);
  cursor: pointer;
  text-align: left;
  color: inherit;
  font: inherit;
}
.pl-card__head { display: flex; align-items: center; justify-content: space-between; }
.pl-card__icon {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: var(--r-md);
  color: var(--cyan);
  background: rgba(34, 211, 238, 0.1);
  border: 1px solid rgba(34, 211, 238, 0.25);
}
.pl-card__name { margin: 14px 0 0; font-size: 16px; }
.pl-card__desc {
  margin: 6px 0 0;
  font-size: 12.5px;
  color: var(--txt-2);
  min-height: 38px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.pl-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--line);
}
.pl-card__code { font-size: 12px; color: var(--txt-1); }
.pl-card__date { font-size: 12px; color: var(--txt-2); }

.pl-card--new {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 180px;
  color: var(--txt-2);
  border-style: dashed;
  background: rgba(148, 163, 184, 0.04);
  transition: color 0.25s, border-color 0.25s, box-shadow 0.25s;
}
.pl-card--new:hover { color: var(--cyan); border-color: rgba(34, 211, 238, 0.45); box-shadow: var(--glow); }
.pl-card__new-hint { font-size: 12px; }
</style>
