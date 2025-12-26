<script setup lang="ts">
defineProps<{
  status: 'healthy' | 'unhealthy' | 'unknown' | 'loading'
}>()
</script>

<template>
  <div :class="[$style.badge, $style[status]]">
    <div v-if="status === 'loading'" :class="$style.spinner"></div>
    <div v-else :class="$style.dot"></div>
    <span :class="$style.text">
      {{ status === 'healthy' ? 'Connected' : status === 'unhealthy' ? 'Error' : status === 'loading' ? 'Checking...' : 'Unknown' }}
    </span>
  </div>
</template>

<style module>
.badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-full);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  border: 1px solid transparent;
}

.dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
}

.healthy {
  background-color: var(--success-bg);
  color: var(--success);
  border-color: var(--success-200);
}
.healthy .dot { background-color: var(--success); }

.unhealthy {
  background-color: var(--danger-bg);
  color: var(--danger);
  border-color: var(--danger-200);
}
.unhealthy .dot { background-color: var(--danger); }

.unknown {
  background-color: var(--bg-tertiary);
  color: var(--text-tertiary);
  border-color: var(--border-default);
}
.unknown .dot { background-color: var(--text-tertiary); }

.loading {
  background-color: var(--primary-100);
  color: var(--primary);
  border-color: var(--primary-200);
}

.spinner {
  width: 0.75rem;
  height: 0.75rem;
  border: 2px solid var(--primary-200);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
