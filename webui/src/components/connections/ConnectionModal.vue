<script setup lang="ts">
import { ref, watch } from 'vue'
import BaseModal from '../shared/BaseModal.vue'
import ProviderForm from '../shared/ProviderForm.vue'
import Button from '../ui/Button.vue'
import Input from '../ui/Input.vue'
import Select from '../ui/Select.vue'
import { useConnectionsStore } from '../../store/connections'
import type { Connection, ConnectionCreate } from '../../types'

const props = defineProps<{
  show: boolean
  connection?: Connection | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const store = useConnectionsStore()
const loading = ref(false)
const error = ref<string | null>(null)

const formData = ref<ConnectionCreate>({
  name: '',
  provider: 'homeassistant',
  config: {}
})

const providerOptions = [
  { value: 'homeassistant', label: 'Home Assistant' },
  { value: 'octoprint', label: 'OctoPrint' },
  { value: 'bambulabs', label: 'BambuLabs' }
]

watch(() => props.connection, (conn) => {
  if (conn) {
    formData.value = {
      name: conn.name,
      provider: conn.provider,
      config: { ...conn.config }
    }
  } else {
    formData.value = {
      name: '',
      provider: 'homeassistant',
      config: {}
    }
  }
}, { immediate: true })

async function handleSave() {
  loading.value = true
  error.value = null
  try {
    if (props.connection) {
      await store.update(props.connection.id, formData.value)
    } else {
      await store.create(formData.value)
    }
    emit('close')
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Failed to save connection'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <BaseModal
    :show="show"
    :title="connection ? 'Edit Connection' : 'Add Connection'"
    @close="emit('close')"
  >
    <form @submit.prevent="handleSave" class="base-form">
      <div class="form-field">
        <label for="connection-name">Connection Name*</label>
        <Input
          id="connection-name"
          v-model="formData.name"
          placeholder="e.g. Workshop OctoPrint"
          required
          :error="!!error"
        />
      </div>

      <div class="form-field">
        <label for="provider">Provider*</label>
        <Select
          id="provider"
          v-model="formData.provider"
          :options="providerOptions"
          :disabled="!!connection"
        />
      </div>

      <div :class="$style.divider"></div>

      <ProviderForm
        :provider="formData.provider"
        v-model="formData.config"
        mode="connection"
      />

      <div v-if="error" class="form-error">{{ error }}</div>
    </form>

    <template #footer>
      <Button variant="ghost" @click="emit('close')">Cancel</Button>
      <Button
        variant="primary"
        @click="handleSave"
        :loading="loading"
      >
        {{ loading ? 'Saving...' : 'Save Connection' }}
      </Button>
    </template>
  </BaseModal>
</template>

<style module>
.divider {
  height: 1px;
  background-color: var(--border-subtle);
  margin: var(--space-4) 0;
}
</style>
