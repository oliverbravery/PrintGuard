import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import { jwtDecode } from 'jwt-decode'

interface TokenPayload {
  sub: string
  scopes: string
  exp: number
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('token'))
  const user = ref<string | null>(localStorage.getItem('user'))
  const scopes = ref<string[]>(JSON.parse(localStorage.getItem('scopes') || '[]'))

  const isAuthenticated = computed(() => !!token.value)
  const isAdmin = computed(() => scopes.value.includes('admin'))

  async function login(username: string, password: string) {
    const formData = new FormData()
    formData.append('username', username)
    formData.append('password', password)

    const response = await axios.post('/api/auth/token', formData)
    const { access_token } = response.data
    
    token.value = access_token
    
    // Decode JWT to get user and scopes
    const decoded = jwtDecode<TokenPayload>(access_token)
    user.value = decoded.sub
    scopes.value = decoded.scopes.split(' ')

    localStorage.setItem('token', token.value!)
    localStorage.setItem('user', user.value!)
    localStorage.setItem('scopes', JSON.stringify(scopes.value))

    // Fetch full user data to ensure we are in sync
    await refreshUser()
  }

  async function refreshUser() {
    if (!token.value) return

    try {
      const response = await axios.get('/api/auth/me', {
        headers: { Authorization: `Bearer ${token.value}` }
      })
      const { username, scopes: userScopes } = response.data
      
      user.value = username
      scopes.value = userScopes
      
      localStorage.setItem('user', user.value!)
      localStorage.setItem('scopes', JSON.stringify(scopes.value))
    } catch (error) {
      console.error('Failed to refresh user data:', error)
      if (axios.isAxiosError(error) && error.response?.status === 401) {
        logout()
      }
    }
  }

  function logout() {
    token.value = null
    user.value = null
    scopes.value = []
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    localStorage.removeItem('scopes')
    window.location.reload()
  }

  return {
    token,
    user,
    scopes,
    isAuthenticated,
    isAdmin,
    login,
    logout,
    refreshUser
  }
})

