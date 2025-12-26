import { ref, computed, watch, onMounted } from 'vue'

const THEME_STORAGE_KEY = 'printguard-theme'
type Theme = 'light' | 'dark'

const theme = ref<Theme>('light')
let isInitialized = false

export function useTheme() {
  const isDark = computed(() => theme.value === 'dark')

  function getSystemTheme(): Theme {
    if (typeof window === 'undefined') return 'light'
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }

  function getStoredTheme(): Theme | null {
    if (typeof window === 'undefined') return null
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    return stored === 'light' || stored === 'dark' ? stored : null
  }

  function setTheme(newTheme: Theme) {
    theme.value = newTheme
    if (typeof window !== 'undefined') {
      localStorage.setItem(THEME_STORAGE_KEY, newTheme)
      document.documentElement.setAttribute('data-theme', newTheme)
    }
  }

  function toggleTheme() {
    setTheme(isDark.value ? 'light' : 'dark')
  }

  function initTheme() {
    if (isInitialized) return

    const stored = getStoredTheme()
    if (stored) {
      setTheme(stored)
    } else {
      setTheme(getSystemTheme())
    }

    isInitialized = true
  }

  function watchSystemTheme() {
    if (typeof window === 'undefined') return

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = (e: MediaQueryListEvent) => {
      if (!getStoredTheme()) {
        setTheme(e.matches ? 'dark' : 'light')
      }
    }

    mediaQuery.addEventListener('change', handler)
    return () => mediaQuery.removeEventListener('change', handler)
  }

  onMounted(() => {
    initTheme()
    watchSystemTheme()
  })

  return {
    theme,
    isDark,
    setTheme,
    toggleTheme,
    initTheme
  }
}

