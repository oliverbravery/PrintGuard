<script setup lang="ts">
import { Sun, Moon } from 'lucide-vue-next'
import { useTheme } from '../../composables/useTheme'

const { isDark, toggleTheme } = useTheme()
</script>

<template>
  <button
    :class="$style.toggle"
    @click="toggleTheme"
    :title="isDark ? 'Switch to light mode' : 'Switch to dark mode'"
    aria-label="Toggle theme"
  >
    <Sun v-if="isDark" :class="$style.icon" />
    <Moon v-else :class="$style.icon" />
  </button>
</template>

<style module>
.toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  color: var(--text-primary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.toggle:hover {
  background-color: var(--bg-tertiary);
  border-color: var(--border-strong);
}

.toggle:active {
  transform: scale(0.95);
}

.icon {
  width: 18px;
  height: 18px;
}
</style>

