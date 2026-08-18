import { defineStore } from 'pinia'
import { authApi, clearToken, getToken, setToken, type User } from '@/api'

const USER_KEY = 'etl_user'

interface AuthState {
  token: string | null
  user: User | null
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    token: getToken(),
    user: JSON.parse(localStorage.getItem(USER_KEY) ?? 'null'),
  }),
  getters: {
    isLoggedIn: (s) => !!s.token,
    displayName: (s) => s.user?.display_name ?? '未登录',
    roles: (s) => s.user?.roles ?? [],
    roleSlots: (s) => s.user?.role_slots ?? [],
  },
  actions: {
    async login(username: string, password: string) {
      const resp = await authApi.login(username, password)
      this.token = resp.token
      this.user = resp.user
      setToken(resp.token)
      localStorage.setItem(USER_KEY, JSON.stringify(resp.user))
    },
    async register(payload: { username: string; password: string; display_name: string; email: string }) {
      await authApi.register(payload)
      // 注册成功后直接登录
      await this.login(payload.username, payload.password)
    },
    async logout() {
      try {
        await authApi.logout()
      } catch {
        /* 注销失败也强制清理本地态 */
      }
      this.token = null
      this.user = null
      clearToken()
      localStorage.removeItem(USER_KEY)
    },
  },
})
