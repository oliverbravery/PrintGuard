<script setup lang="ts">
import { ref, watch } from 'vue'
import BaseModal from './BaseModal.vue'
import Button from '../ui/Button.vue'

const props = defineProps<{
  show: boolean
  title: string
  itemName: string
  itemType: string
  usageItems: any[]
  usageLabel: string
  cascadeLabel?: string
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'confirm', cascade: boolean): void
}>()

const cascade = ref(false)

watch(() => props.show, (show) => {
  if (show) {
    cascade.value = false
  }
})
</script>

<template>
  <BaseModal :show="show" :title="title" @close="emit('close')" size="sm">
    <div :class="$style.content">
      <p>Are you sure you want to delete {{ itemType }} <strong>{{ itemName }}</strong>?</p>

      <div v-if="usageItems.length > 0" :class="$style.warning">
        <p>⚠️ <strong>Warning:</strong> {{ usageLabel }}</p>
        <ul :class="$style.list">
          <slot name="usage" :items="usageItems"></slot>
        </ul>
        <label v-if="cascadeLabel" :class="$style.checkboxLabel">
          <input type="checkbox" v-model="cascade" />
          {{ cascadeLabel }}
        </label>
      </div>
      <p v-else-if="!loading" :class="$style.safe">This {{ itemType }} is not in use.</p>
    </div>

    <template #footer>
      <Button variant="ghost" @click="emit('close')">Cancel</Button>
      <Button
        variant="danger"
        @click="emit('confirm', cascade)"
        :loading="loading"
      >
        {{ loading ? 'Deleting...' : 'Delete' }}
      </Button>
    </template>
  </BaseModal>
</template>

<style module>
.content {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.content p {
  color: var(--text-primary);
  font-size: var(--font-size-base);
}

.content strong {
  font-weight: var(--font-weight-semibold);
}

.warning {
  padding: var(--space-4);
  background-color: var(--warning-bg);
  border: 1px solid var(--warning-200);
  border-radius: var(--radius-lg);
  font-size: var(--font-size-sm);
}

.warning p {
  color: var(--warning);
  margin-bottom: var(--space-2);
}

.list {
  margin: var(--space-2) 0 var(--space-4) var(--space-6);
  list-style: disc;
  color: var(--text-secondary);
}

.checkboxLabel {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  color: var(--text-primary);
}

.checkboxLabel input[type="checkbox"] {
  width: 1rem;
  height: 1rem;
  cursor: pointer;
}

.safe {
  color: var(--success);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
}
</style>
