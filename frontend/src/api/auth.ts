import { get, post } from './client'
import type { LoginResp, User } from './types'

export const authApi = {
  login(username: string, password: string) {
    return post<LoginResp>('/auth/login', { username, password })
  },
  register(payload: {
    username: string
    password: string
    display_name: string
    email: string
  }) {
    return post<User>('/auth/register', payload)
  },
  logout() {
    return post<void>('/auth/logout')
  },
}

export { get }
