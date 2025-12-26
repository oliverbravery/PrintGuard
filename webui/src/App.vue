<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
import { useAuthStore } from './store/auth'
import { useSystemStore } from './store/system'
import { useTheme } from './composables/useTheme'
import ConnectionError from './components/shared/ConnectionError.vue'
import ThemeToggle from './components/ui/ThemeToggle.vue'

const auth = useAuthStore()
const system = useSystemStore()
const { initTheme } = useTheme()

initTheme()

function reload() {
  window.location.reload()
}
</script>

<template>
  <div :class="$style.app">
    <template v-if="system.isApiDown">
      <div :class="$style.apiDown">
        <ConnectionError
          title="PrintGuard Offline"
          :message="system.lastError || undefined"
          @retry="reload"
        />
      </div>
    </template>

    <template v-else>
      <nav v-if="auth.isAuthenticated" :class="$style.nav">
        <div :class="$style.container">
          <div :class="$style.logo">PrintGuard</div>
          <div :class="$style.links">
            <RouterLink to="/" :class="$style.link" active-class="active">Dashboard</RouterLink>
            <RouterLink to="/connections" :class="$style.link" active-class="active">Connections</RouterLink>
            <RouterLink to="/components" :class="$style.link" active-class="active">Components</RouterLink>
            <RouterLink to="/settings" :class="$style.link" active-class="active">Settings</RouterLink>
            <ThemeToggle :class="$style.themeToggle" />
            <button @click="auth.logout()" :class="$style.logout">Logout</button>
          </div>
        </div>
      </nav>

      <main :class="$style.main">
        <div :class="$style.container">
          <RouterView />
        </div>
      </main>
    </template>
  </div>
</template>

<style module>
.app {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.apiDown {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--bg-primary);
}

.nav {
  background-color: var(--card-bg);
  border-bottom: 1px solid var(--border-subtle);
  padding: var(--space-4) 0;
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
  box-shadow: var(--shadow-sm);
}

.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 var(--space-6);
  width: 100%;
}

.nav .container {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.logo {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-extrabold);
  color: var(--primary);
  letter-spacing: var(--letter-spacing-tight);
}

.links {
  display: flex;
  align-items: center;
  gap: var(--space-6);
}

.link {
  color: var(--text-secondary);
  font-weight: var(--font-weight-medium);
  font-size: var(--font-size-sm);
  transition: color var(--transition-fast);
  position: relative;
}

.link:hover {
  color: var(--text-primary);
}

.link :global(.active) {
  color: var(--primary);
}

.link :global(.active)::after {
  content: '';
  position: absolute;
  bottom: calc(-1 * var(--space-5));
  left: 0;
  right: 0;
  height: 2px;
  background-color: var(--primary);
  border-radius: var(--radius-full);
}

.themeToggle {
  margin-left: var(--space-2);
}

.logout {
  color: var(--danger);
  font-weight: var(--font-weight-medium);
  font-size: var(--font-size-sm);
  margin-left: var(--space-4);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-lg);
  transition: all var(--transition-fast);
}

.logout:hover {
  background-color: var(--danger-bg);
}

.main {
  flex: 1;
  padding: var(--space-8) 0;
}
</style>
