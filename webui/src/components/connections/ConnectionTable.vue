<script setup lang="ts">
import HealthBadge from '../shared/HealthBadge.vue'
import IconButton from '../ui/IconButton.vue'
import { Search, Edit, Trash2 } from 'lucide-vue-next'
import type { Connection } from '../../types'

defineProps<{
  connections: Connection[]
}>()

const emit = defineEmits<{
  (e: 'edit', connection: Connection): void
  (e: 'delete', connection: Connection): void
  (e: 'browse', connection: Connection): void
}>()
</script>

<template>
  <div class="table-container">
    <table class="base-table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Provider</th>
          <th>Host / URL</th>
          <th>Health</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="conn in connections" :key="conn.id">
          <td :class="$style.name">{{ conn.name }}</td>
          <td>
            <span :class="$style.providerBadge">{{ conn.provider }}</span>
          </td>
          <td :class="$style.url">{{ conn.config.hass_url || conn.config.host || 'N/A' }}</td>
          <td>
            <HealthBadge status="healthy" />
          </td>
          <td>
            <div class="table-actions">
              <IconButton
                variant="ghost"
                size="sm"
                title="Browse Entities"
                @click="emit('browse', conn)"
              >
                <Search />
              </IconButton>
              <IconButton
                variant="ghost"
                size="sm"
                title="Edit"
                @click="emit('edit', conn)"
              >
                <Edit />
              </IconButton>
              <IconButton
                variant="danger"
                size="sm"
                title="Delete"
                @click="emit('delete', conn)"
              >
                <Trash2 />
              </IconButton>
            </div>
          </td>
        </tr>
        <tr v-if="connections.length === 0">
          <td colspan="5" class="table-empty">No connections setup yet.</td>
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

.url {
  font-family: monospace;
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
}
</style>
