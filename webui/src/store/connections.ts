import { defineStore } from 'pinia'
import { ref } from 'vue'
import { connectionsApi } from '../services/api'
import type { Connection, ConnectionCreate, ConnectionUpdate } from '../types'

export const useConnectionsStore = defineStore('connections', () => {
  const connections = ref<Connection[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchAll(provider?: string) {
    loading.value = true
    error.value = null
    try {
      const response = await connectionsApi.list(provider)
      connections.value = response.data
    } catch (e: any) {
      error.value = e.response?.data?.detail || 'Failed to fetch connections'
      console.error(e)
    } finally {
      loading.value = false
    }
  }

  async function create(data: ConnectionCreate) {
    const response = await connectionsApi.create(data)
    connections.value.push(response.data)
    return response.data
  }

  async function update(id: string, data: ConnectionUpdate) {
    const response = await connectionsApi.update(id, data)
    const index = connections.value.findIndex(c => c.id === id)
    if (index !== -1) {
      connections.value[index] = response.data
    }
    return response.data
  }

  async function remove(id: string, cascade = false) {
    await connectionsApi.delete(id, cascade)
    connections.value = connections.value.filter(c => c.id !== id)
  }

  return {
    connections,
    loading,
    fetchAll,
    create,
    update,
    remove
  }
})

