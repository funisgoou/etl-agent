<template>
  <div class="login">
    <div class="app-bg" />

    <!-- 左侧品牌区 -->
    <section class="login__brand rise-in">
      <div class="login__logo-row">
        <span class="login__logo" />
        <span class="grad-text login__wordmark">ETL·Agent</span>
      </div>
      <h1 class="login__slogan">
        让数据入仓，<br /><span class="grad-text">像对话一样简单。</span>
      </h1>
      <ul class="login__features">
        <li v-for="f in features" :key="f.title">
          <span class="login__feature-dot" />
          <div>
            <p class="login__feature-title">{{ f.title }}</p>
            <p class="login__feature-desc">{{ f.desc }}</p>
          </div>
        </li>
      </ul>
      <div class="login__health">
        <span
          v-for="(st, name) in app.health?.components ?? {}"
          :key="name"
          class="dot"
          :class="{ 'is-live': st === 'ok' }"
          :style="{ background: st === 'ok' ? 'var(--green)' : 'var(--amber)' }"
          :title="`${name}: ${st}`"
        />
        <span class="login__health-text">{{ app.healthOk ? '全部组件就绪' : '组件探测中…' }}</span>
      </div>
    </section>

    <!-- 右侧表单卡片 -->
    <section class="login__panel">
      <div class="login__card glass rise-in">
        <el-tabs v-model="tab" stretch class="login__tabs">
          <el-tab-pane label="登录" name="login" />
          <el-tab-pane label="注册" name="register" />
        </el-tabs>

        <el-form v-if="tab === 'login'" @submit.prevent="submitLogin">
          <el-form-item>
            <el-input v-model="loginForm.username" size="large" placeholder="用户名（演示：任意）" :prefix-icon="User" />
          </el-form-item>
          <el-form-item>
            <el-input v-model="loginForm.password" size="large" type="password" show-password placeholder="密码（演示：任意）" :prefix-icon="Lock" @keyup.enter="submitLogin" />
          </el-form-item>
          <el-button class="login__submit" type="primary" size="large" :loading="loading" @click="submitLogin">
            进入观测站
          </el-button>
        </el-form>

        <el-form v-else @submit.prevent="submitRegister">
          <el-form-item>
            <el-input v-model="regForm.username" size="large" placeholder="用户名" :prefix-icon="User" />
          </el-form-item>
          <el-form-item>
            <el-input v-model="regForm.display_name" size="large" placeholder="显示名称" :prefix-icon="Postcard" />
          </el-form-item>
          <el-form-item>
            <el-input v-model="regForm.email" size="large" placeholder="邮箱" :prefix-icon="Message" />
          </el-form-item>
          <el-form-item>
            <el-input v-model="regForm.password" size="large" type="password" show-password placeholder="密码" :prefix-icon="Lock" @keyup.enter="submitRegister" />
          </el-form-item>
          <el-button class="login__submit" type="primary" size="large" :loading="loading" @click="submitRegister">
            注册并进入
          </el-button>
        </el-form>

        <p class="login__tip">
          {{ mockEnabled ? '演示环境：Mock 已启用，任意账号密码即可登录' : '已连接真实后端，请使用平台账号登录' }}
        </p>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Lock, Message, Postcard, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useProjectStore } from '@/stores/project'
import { MOCK_ENABLED } from '@/mock'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const app = useAppStore()
const projectStore = useProjectStore()

const tab = ref<'login' | 'register'>('login')
const loading = ref(false)
const mockEnabled = MOCK_ENABLED
const loginForm = reactive({ username: 'zhangwei', password: '' })
const regForm = reactive({ username: '', password: '', display_name: '', email: '' })

const features = [
  { title: '对话式生成 ETL 配置', desc: '意图解析 → 元数据探查 → HOCON 生成，全程门禁护航' },
  { title: '三阶段安全协议', desc: 'Prepare / Approve / Commit，四眼审批 + 单次 Capability' },
  { title: '证据账本可验真', desc: '哈希链追加写入，篡改断点一键定位' },
]

onMounted(() => app.refreshHealth())

async function afterLogin() {
  await projectStore.fetchList()
  const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
  router.push(redirect || `/p/${projectStore.currentId}/dashboard`)
}

async function submitLogin() {
  if (!loginForm.username || !loginForm.password) {
    ElMessage.warning('请输入用户名与密码')
    return
  }
  loading.value = true
  try {
    await auth.login(loginForm.username, loginForm.password)
    await afterLogin()
  } catch (e: any) {
    ElMessage.error(e?.message ?? '登录失败')
  } finally {
    loading.value = false
  }
}

async function submitRegister() {
  if (!regForm.username || !regForm.password || !regForm.display_name) {
    ElMessage.warning('用户名 / 显示名称 / 密码必填')
    return
  }
  loading.value = true
  try {
    await auth.register({ ...regForm })
    ElMessage.success('注册成功')
    await afterLogin()
  } catch (e: any) {
    ElMessage.error(e?.message ?? '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 1.15fr 1fr;
}

/* 左侧品牌区 */
.login__brand {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 8vh 7vw;
}
.login__logo-row { display: flex; align-items: center; gap: 12px; margin-bottom: 6vh; }
.login__logo {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: var(--grad);
  box-shadow: var(--glow-strong);
}
.login__wordmark { font-size: 20px; font-weight: 700; }
.login__slogan {
  font-size: clamp(34px, 3.6vw, 52px);
  line-height: 1.25;
  letter-spacing: 0.01em;
  margin-bottom: 5vh;
}
.login__features { list-style: none; margin: 0 0 6vh; padding: 0; display: grid; gap: 22px; }
.login__features li { display: flex; gap: 14px; align-items: flex-start; }
.login__feature-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--grad);
  margin-top: 8px;
  flex: none;
  box-shadow: var(--glow);
}
.login__feature-title { margin: 0; font-size: 15px; color: var(--txt-0); }
.login__feature-desc { margin: 2px 0 0; font-size: 13px; color: var(--txt-1); }
.login__health { display: flex; align-items: center; gap: 7px; }
.login__health-text { font-size: 12px; color: var(--txt-2); margin-left: 6px; }

/* 右侧表单 */
.login__panel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 6vh 5vw;
}
.login__card {
  width: 100%;
  max-width: 400px;
  padding: 34px 32px 26px;
  border-radius: var(--r-lg);
  box-shadow: 0 24px 80px rgba(2, 6, 16, 0.6);
}
.login__tabs { margin-bottom: 22px; }
.login__submit {
  width: 100%;
  margin-top: 6px;
  letter-spacing: 0.12em;
}
.login__tip {
  margin: 18px 0 0;
  text-align: center;
  font-size: 12px;
  color: var(--txt-2);
}

@media (max-width: 900px) {
  .login { grid-template-columns: 1fr; }
  .login__brand { display: none; }
}
</style>
