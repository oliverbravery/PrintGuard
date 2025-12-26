import { defineStore } from 'pinia'
import { ref } from 'vue'
import { printersApi } from '../services/api'
import type { Printer, PrinterCreate, PrinterUpdate } from '../types'

export const usePrintersStore = defineStore('printers', () => {
  const printers = ref<Printer[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchAll() {
    loading.value = true
    error.value = null
    try {
      const response = await printersApi.list()
      printers.value = response.data
    } catch (e: any) {
      error.value = e.response?.data?.detail || 'Failed to fetch printers'
      console.error(e)
    } finally {
      loading.value = false
    }
  }

  async function create(data: PrinterCreate) {
    const response = await printersApi.create(data)
    printers.value.push(response.data)
    return response.data
  }

  async function update(id: string, data: PrinterUpdate) {
    const response = await printersApi.update(id, data)
    const index = printers.value.findIndex(p => p.id === id)
    if (index !== -1) {
      printers.value[index] = response.data
    }
    return response.data
  }

  async function remove(id: string) {
    await printersApi.delete(id)
    printers.value = printers.value.filter(p => p.id !== id)
  }

  async function sendCommand(id: string, cmd: string) {
    await printersApi.command(id, cmd)
    // Refresh the printer status
    const response = await printersApi.get(id)
    const index = printers.value.findIndex(p => p.id === id)
    if (index !== -1) {
      printers.value[index] = response.data
    }
  }

  return {
    printers,
    loading,
    fetchAll,
    create,
    update,
    remove,
    sendCommand
  }
})

