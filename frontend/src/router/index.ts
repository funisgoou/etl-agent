import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { getToken } from '@/api'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/login/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    component: () => import('@/layout/AppShell.vue'),
    children: [
      { path: '', redirect: () => shellRedirect() },
      {
        path: 'p/:projectId/dashboard',
        name: 'dashboard',
        component: () => import('@/views/dashboard/DashboardView.vue'),
        meta: { title: '总览工作台' },
      },
      {
        path: 'p/:projectId/connections',
        name: 'connections',
        component: () => import('@/views/connections/ConnectionsView.vue'),
        meta: { title: '数据资产' },
      },
      {
        path: 'p/:projectId/studio',
        name: 'studio',
        component: () => import('@/views/studio/StudioList.vue'),
        meta: { title: 'Pipeline Studio' },
      },
      {
        path: 'p/:projectId/studio/pipeline/:pipelineId',
        name: 'studio-pipeline',
        component: () => import('@/views/studio/StudioView.vue'),
        meta: { title: 'Pipeline Studio' },
      },
      {
        path: 'p/:projectId/runs',
        name: 'runs',
        component: () => import('@/views/runs/RunsView.vue'),
        meta: { title: '运行中心' },
      },
      {
        path: 'p/:projectId/governance',
        name: 'governance',
        component: () => import('@/views/governance/GovernanceView.vue'),
        meta: { title: '安全治理' },
      },
      {
        path: 'p/:projectId/audit',
        name: 'audit',
        component: () => import('@/views/audit/AuditView.vue'),
        meta: { title: '审计' },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

/** `/` 重定向到当前项目 dashboard */
function shellRedirect(): string {
  const pid = localStorage.getItem('etl_project_id') || '1'
  return `/p/${pid}/dashboard`
}

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const token = getToken()

  // 无 token → /login
  if (!token && !to.meta.public) {
    return { path: '/login', query: to.fullPath !== '/' ? { redirect: to.fullPath } : {} }
  }
  // 已登录访问 /login → 回项目
  if (token && to.path === '/login') {
    return shellRedirect()
  }

  // 进入外壳：无 projectId 或非法 → 替换为当前项目
  if (to.path.startsWith('/p/')) {
    const pid = Number(to.params.projectId)
    if (!Number.isFinite(pid) || pid <= 0) {
      return shellRedirect()
    }
    // 与 project store 的 currentId 对齐（路由为真相源之一）
    localStorage.setItem('etl_project_id', String(pid))
  }
  return true
})
