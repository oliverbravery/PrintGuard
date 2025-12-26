<script setup lang="ts">
import { useAuthStore } from '../store/auth'
import TunnelConfig from '../components/settings/TunnelConfig.vue'
import UserList from '../components/settings/UserList.vue'
import M2MList from '../components/settings/M2MList.vue'

const auth = useAuthStore()
</script>

<template>
  <div :class="$style.view">
    <header :class="$style.header">
      <div>
        <h1>Settings</h1>
        <p :class="$style.subtitle">System configuration and access control.</p>
      </div>
    </header>

    <div :class="$style.sections">
      <section :class="$style.section">
        <h2>Remote Access</h2>
        <TunnelConfig />
      </section>

      <template v-if="auth.isAdmin">
        <section :class="$style.section">
          <h2>User Management</h2>
          <UserList />
        </section>

        <section :class="$style.section">
          <h2>API Access</h2>
          <M2MList />
        </section>
      </template>
    </div>
  </div>
</template>

<style module>
.view {
  display: flex;
  flex-direction: column;
  gap: var(--space-10);
}

.header h1 {
  font-size: var(--font-size-3xl);
  letter-spacing: var(--letter-spacing-tight);
}

.subtitle {
  color: var(--text-secondary);
  font-size: var(--font-size-base);
  margin-top: var(--space-2);
}

.sections {
  display: flex;
  flex-direction: column;
  gap: var(--space-16);
}

.section {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.section h2 {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-bold);
  color: var(--text-primary);
  border-left: 4px solid var(--primary);
  padding-left: var(--space-4);
}
</style>
