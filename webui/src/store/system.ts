import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useSystemStore = defineStore('system', () => {
  const isApiDown = ref(false)
  const lastError = ref<string | null>(null)

  function setApiDown(error: string) {
    isApiDown.value = true
    lastError.value = error
  }

  function setApiUp() {
    isApiDown.value = false
    lastError.value = null
  }

  return {
    isApiDown,
    lastError,
    setApiDown,
    setApiUp
  }
})

