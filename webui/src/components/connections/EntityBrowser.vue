<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { connectionsApi } from '../../services/api'
import Badge from '../ui/Badge.vue'
import type { Entity } from '../../types'

const props = defineProps<{
  connectionId: string
  type?: string
}>()

const emit = defineEmits<{
  (e: 'select', entity: Entity): void
}>()

const entities = ref<Entity[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

async function fetchEntities() {
  loading.value = true
  error.value = null
  try {
    const response = await connectionsApi.entities(props.connectionId, props.type)
    entities.value = response.data
  } catch (e) {
    error.value = 'Failed to fetch entities'
  } finally {
    loading.value = false
  }
}

onMounted(fetchEntities)
</script>

<template>
  <div :class="$style.browser">
    <div v-if="loading" :class="$style.loading">Scanning for entities...</div>
    <div v-else-if="error" :class="$style.error">{{ error }}</div>
    <div v-else :class="$style.list">
      <div 
        v-for="entity in entities" 
        :key="entity.id" 
        :class="$style.item"
        @click="emit('select', entity)"
      >
        <div :class="$style.info">
          <span :class="$style.name">{{ entity.name }}</span>
          <span :class="$style.id">{{ entity.id }}</span>
        </div>
        <Badge variant="neutral" size="sm">{{ entity.type }}</Badge>
      </div>
      <div v-if="entities.length === 0" :class="$style.empty">
        No entities found for this connection.
      </div>
    </div>
  </div>
</template>

<style module>
.browser {
  background-color: var(--bg-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  max-height: 300px;
  overflow-y: auto;
  box-shadow: var(--shadow-sm);
}

.list {
  display: flex;
  flex-direction: column;
}

.item {
  padding: var(--space-3) var(--space-4);
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  transition: all var(--transition-fast);
  border-bottom: 1px solid var(--border-subtle);
}

.item:last-child {
  border-bottom: none;
}

.item:hover {
  background-color: var(--bg-secondary);
}

.info {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.name {
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
}

.id {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
  font-family: monospace;
}

.loading, .error, .empty {
  padding: var(--space-8);
  text-align: center;
  color: var(--text-tertiary);
  font-size: var(--font-size-sm);
}

.error {
  color: var(--danger);
}
</style>

