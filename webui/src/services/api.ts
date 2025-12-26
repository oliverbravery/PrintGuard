import axios from 'axios'
import { useSystemStore } from '../store/system'
import type { 
  Connection, ConnectionCreate, ConnectionUpdate,
  Component, ComponentCreate, ComponentUpdate,
  Printer, PrinterCreate, PrinterUpdate,
  HealthStatus, Entity, ProviderSchema,
  User, M2MApplication
} from '../types'

const api = axios.create({
  baseURL: '/api'
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => {
    const system = useSystemStore()
    system.setApiUp()
    return response
  },
  (error) => {
    const system = useSystemStore()
    
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      localStorage.removeItem('scopes')
      window.location.href = '/login'
    } else if (!error.response || error.response.status >= 500) {
      system.setApiDown(error.response?.data?.detail || 'The PrintGuard API is currently unavailable.')
    }
    
    return Promise.reject(error)
  }
)

export const connectionsApi = {
  list: (provider?: string) => api.get<Connection[]>('/connections', { params: { provider } }),
  get: (id: string) => api.get<Connection>(`/connections/${id}`),
  create: (data: ConnectionCreate) => api.post<Connection>('/connections', data),
  update: (id: string, data: ConnectionUpdate) => api.put<Connection>(`/connections/${id}`, data),
  delete: (id: string, cascade = false) => api.delete(`/connections/${id}`, { params: { cascade } }),
  health: (id: string) => api.get<HealthStatus>(`/connections/${id}/health`),
  components: (id: string) => api.get<Component[]>(`/connections/${id}/components`),
  entities: (id: string, type?: string) => api.get<Entity[]>(`/connections/${id}/entities`, { params: { type } })
}

export const componentsApi = {
  list: (filters?: any) => api.get<Component[]>('/components', { params: filters }),
  get: (id: string) => api.get<Component>(`/components/${id}`),
  create: (data: ComponentCreate) => api.post<Component>('/components', data),
  update: (id: string, data: ComponentUpdate) => api.put<Component>(`/components/${id}`, data),
  delete: (id: string, force = false) => api.delete(`/components/${id}`, { params: { force } }),
  health: (id: string) => api.get<HealthStatus>(`/components/${id}/health`),
  printers: (id: string) => api.get<any[]>(`/components/${id}/printers`),
  stream: (id: string, sessionId: string) => api.post(`/components/${id}/stream`, {}, { params: { session_id: sessionId } })
}

export const printersApi = {
  list: () => api.get<Printer[]>('/printer'),
  get: (id: string) => api.get<Printer>(`/printer/${id}`),
  create: (data: PrinterCreate) => api.post<Printer>('/printer', data),
  update: (id: string, data: PrinterUpdate) => api.put<Printer>(`/printer/${id}`, data),
  delete: (id: string) => api.delete(`/printer/${id}`),
  command: (id: string, cmd: string) => api.post(`/printer/${id}/${cmd}`),
  stream: (id: string, sessionId: string) => api.post(`/printer/${id}/stream`, {}, { params: { session_id: sessionId } }),
  providers: () => api.get<string[]>('/printer/providers'),
  providerSchema: (provider: string) => api.get<ProviderSchema>(`/printer/providers/${provider}/schema`)
}

export const streamsApi = {
  list: () => api.get<any[]>('/rtc/streams'),
  view: (sessionId: string, offer: any) => api.post(`/rtc/view/${sessionId}`, offer),
  offer: (offer: any) => api.post('/rtc/offer', offer),
  snapshot: (sessionId: string) => api.get(`/rtc/snapshot/${sessionId}`, { responseType: 'blob' }),
  result: (sessionId: string) => api.get(`/rtc/result/${sessionId}`),
  close: (sessionId: string) => api.delete(`/rtc/${sessionId}`)
}

export const adminApi = {
  listUsers: () => api.get<User[]>('/admin/users'),
  deleteUser: (username: string) => api.delete(`/admin/users/${username}`),
  createUser: (data: any) => api.post<User>('/admin/users', data),
  listM2M: () => api.get<M2MApplication[]>('/admin/m2m'),
  deleteM2M: (clientId: string) => api.delete(`/admin/m2m/${clientId}`),
  createM2M: (data: any) => api.post<M2MApplication>('/admin/m2m', data)
}

export const tunnelApi = {
  status: () => api.get('/tunnel/status'),
  disable: () => api.post('/tunnel/disable'),
  checkDependencies: () => api.get('/tunnel/check-dependencies')
}

export const ngrokApi = {
  setup: (data: any) => api.post('/ngrok/tunnel', data)
}

export const cloudflareApi = {
  validateToken: (token: string) => api.get('/cloudflare/validate-token', { params: { api_token: token } }),
  accounts: (token: string) => api.get('/cloudflare/accounts', { params: { api_token: token } }),
  zones: (token: string) => api.get('/cloudflare/zones', { params: { api_token: token } }),
  checkExistence: (params: any) => api.get('/cloudflare/check-existence', { params }),
  setup: (token: string, data: any) => api.post('/cloudflare/tunnel', data, { params: { api_token: token } })
}

export default api

