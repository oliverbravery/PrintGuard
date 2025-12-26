<script setup lang="ts">
import HealthBadge from '../shared/HealthBadge.vue'
import IconButton from '../ui/IconButton.vue'
import Badge from '../ui/Badge.vue'
import { Eye, Edit, Trash2 } from 'lucide-vue-next'
import type { Component } from '../../types'

defineProps<{
  components: Component[]
}>()

const emit = defineEmits<{
  (e: 'edit', component: Component): void
  (e: 'delete', component: Component): void
  (e: 'preview', component: Component): void
}>()
</script>

<template>
  <div class="table-container">
    <table class="base-table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Type</th>
          <th>Provider</th>
          <th>Connection</th>
          <th>Health</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="comp in components" :key="comp.id">
          <td :class="$style.name">{{ comp.name }}</td>
          <td>
            <Badge :variant="comp.type === 'camera' ? 'primary' : comp.type === 'control' ? 'success' : 'warning'" size="sm">
              {{ comp.type }}
            </Badge>
          </td>
          <td>
            <span :class="$style.providerBadge">{{ comp.provider }}</span>
          </td>
          <td>
            <span v-if="comp.connection" :class="$style.connectionName">{{ comp.connection.name }}</span>
            <span v-else :class="$style.standalone">Standalone</span>
          </td>
          <td>
            <HealthBadge status="healthy" />
          </td>
          <td>
            <div class="table-actions">
              <IconButton
                v-if="comp.type === 'camera'"
                variant="ghost"
                size="sm"
                title="Live Preview"
                @click="emit('preview', comp)"
              >
                <Eye />
              </IconButton>
              <IconButton
                variant="ghost"
                size="sm"
                title="Edit"
                @click="emit('edit', comp)"
              >
                <Edit />
              </IconButton>
              <IconButton
                variant="danger"
                size="sm"
                title="Delete"
                @click="emit('delete', comp)"
              >
                <Trash2 />
              </IconButton>
            </div>
          </td>
        </tr>
        <tr v-if="components.length === 0">
          <td colspan="6" class="table-empty">No components found matching filters.</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style module>
.name {
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
}

.providerBadge {
  font-size: var(--font-size-xs);
  background-color: var(--bg-tertiary);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-md);
  text-transform: uppercase;
  font-weight: var(--font-weight-semibold);
  letter-spacing: var(--letter-spacing-wide);
  color: var(--text-secondary);
}

.connectionName {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
}

.standalone {
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
  font-style: italic;
}
</style>
