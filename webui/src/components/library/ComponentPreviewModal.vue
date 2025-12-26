<script setup lang="ts">
import { ref, watch } from 'vue'
import BaseModal from '../shared/BaseModal.vue'
import CameraFeed from '../shared/CameraFeed.vue'
import type { Component } from '../../types'

const props = defineProps<{
  show: boolean
  component: Component | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

function close() {
  emit('close')
}
</script>

<template>
  <BaseModal 
    :show="show" 
    :title="`Preview: ${component?.name || 'Camera'}`" 
    size="lg"
    @close="close"
  >
    <div :class="$style.content">
      <CameraFeed v-if="show && component" :component="component" />
    </div>

    <template #footer>
      <button :class="$style.closeBtn" @click="close">Close</button>
    </template>
  </BaseModal>
</template>

<style module>
.content {
  width: 100%;
}

.closeBtn {
  padding: 0.75rem 1.5rem;
  background-color: var(--border);
  color: var(--text);
  border-radius: 0.5rem;
  font-weight: 600;
}

</style>

