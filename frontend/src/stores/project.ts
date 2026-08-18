import { defineStore } from 'pinia'
import { projectApi, type Project } from '@/api'

const PROJECT_KEY = 'etl_project_id'

interface ProjectState {
  list: Project[]
  currentId: number | null
  loaded: boolean
}

export const useProjectStore = defineStore('project', {
  state: (): ProjectState => ({
    list: [],
    currentId: Number(localStorage.getItem(PROJECT_KEY)) || null,
    loaded: false,
  }),
  getters: {
    current: (s): Project | null => s.list.find((p) => p.id === s.currentId) ?? s.list[0] ?? null,
  },
  actions: {
    async fetchList() {
      const resp = await projectApi.list({ page: 1, page_size: 100 })
      this.list = resp.items
      this.loaded = true
      if (!this.currentId || !this.list.some((p) => p.id === this.currentId)) {
        this.currentId = this.list[0]?.id ?? null
      }
      if (this.currentId) localStorage.setItem(PROJECT_KEY, String(this.currentId))
    },
    /** 切换项目并返回项目 id（由调用方同步路由） */
    switchTo(id: number): number {
      this.currentId = id
      localStorage.setItem(PROJECT_KEY, String(id))
      return id
    },
    async createProject(payload: { name: string; code: string; description?: string }) {
      const p = await projectApi.create(payload)
      this.list.push(p)
      this.switchTo(p.id)
      return p
    },
  },
})
