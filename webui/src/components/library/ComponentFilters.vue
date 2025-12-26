<script setup lang="ts">
import { ref, computed } from 'vue'
import { useConnectionsStore } from '../../store/connections'
import Select from '../ui/Select.vue'

const emit = defineEmits<{
  (e: 'change', filters: any): void
}>()

const connStore = useConnectionsStore()
const typeFilter = ref('All')
const providerFilter = ref('All')
const connectionFilter = ref('All')

const providers = ['All', 'homeassistant', 'octoprint', 'bambulabs', 'webrtc', 'webcam']
const providerOptions = providers.map(p => ({ value: p, label: p }))

const connectionOptions = computed(() => [
  { value: 'All', label: 'All Connections' },
  ...connStore.connections.map(c => ({ value: c.id, label: c.name }))
])

function update() {
  const filters: any = {}
  if (typeFilter.value !== 'All') filters.type = typeFilter.value.toLowerCase()
  if (providerFilter.value !== 'All') filters.provider = providerFilter.value
  if (connectionFilter.value !== 'All') filters.connection_id = connectionFilter.value
  emit('change', filters)
}
</script>

<template>
  <div :class="$style.filters">
    <div :class="$style.group">
      <label>Type</label>
      <div :class="$style.chips">
        <button 
          v-for="t in ['All', 'Camera', 'Control', 'Status']" 
          :key="t"
          :class="[$style.chip, { [$style.active]: typeFilter === t }]"
          @click="typeFilter = t; update()"
        >
          {{ t }}
        </button>
      </div>
    </div>

    <div :class="$style.group">
      <label>Provider</label>
      <Select 
        v-model="providerFilter" 
        :options="providerOptions" 
        size="sm"
        @change="update"
      />
    </div>

    <div :class="$style.group">
      <label>Connection</label>
      <Select 
        v-model="connectionFilter" 
        :options="connectionOptions" 
        size="sm"
        @change="update"
      />
    </div>
  </div>
</template>

<style module>
.filters {
  display: flex;
  align-items: flex-end;
  gap: var(--space-8);
  padding: var(--space-6);
  background-color: var(--card-bg);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
}

.group {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.group label {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-bold);
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: var(--letter-spacing-wide);
}

.chips {
  display: flex;
  gap: var(--space-2);
}

.chip {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-full);
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-default);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--text-secondary);
  transition: all var(--transition-fast);
}

.chip:hover {
  border-color: var(--border-strong);
  background-color: var(--bg-tertiary);
}

.chip.active {
  background-color: var(--primary);
  color: var(--primary-on);
  border-color: var(--primary);
}
</style>

