import { defineStore } from 'pinia'
import { getHealth, type HealthResp } from '@/api'

interface AppState {
  health: HealthResp | null
  healthAt: number | null
}

/** 全局应用态：组件健康轮询等 */
export const useAppStore = defineStore('app', {
  state: (): AppState => ({
    health: null,
    healthAt: null,
  }),
  getters: {
    healthOk: (s) => s.health?.status === 'ok',
  },
  actions: {
    async refreshHealth() {
      try {
        this.health = await getHealth()
      } catch {
        this.health = { status: 'degraded', components: {} }
      }
      this.healthAt = Date.now()
    },
  },
})
