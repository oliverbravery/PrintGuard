<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import BaseModal from '../shared/BaseModal.vue'
import ProviderForm from '../shared/ProviderForm.vue'
import EntityBrowser from '../connections/EntityBrowser.vue'
import Button from '../ui/Button.vue'
import Input from '../ui/Input.vue'
import Badge from '../ui/Badge.vue'
import { useComponentsStore } from '../../store/components'
import { useConnectionsStore } from '../../store/connections'
import type { Component, ComponentCreate } from '../../types'

const props = defineProps<{
  show: boolean
  component?: Component | null
  initialType?: 'camera' | 'control' | 'status'
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'created', component: Component): void
}>()

const store = useComponentsStore()
const connStore = useConnectionsStore()
const loading = ref(false)
const error = ref<string | null>(null)
const step = ref(1)

const formData = ref<ComponentCreate>({
  name: '',
  type: 'camera',
  provider: 'homeassistant',
  connection_id: undefined,
  entity_config: {}
})

const selectedConnection = computed(() =>
  connStore.connections.find(c => c.id === formData.value.connection_id)
)

watch(() => props.show, (show) => {
  if (show) {
    if (props.component) {
      formData.value = {
        name: props.component.name,
        type: props.component.type,
        provider: props.component.provider,
        connection_id: props.component.connection_id,
        entity_config: { ...props.component.entity_config }
      }
      step.value = 3
    } else {
      formData.value = {
        name: '',
        type: props.initialType || 'camera',
        provider: 'homeassistant',
        connection_id: undefined,
        entity_config: {}
      }
      step.value = 1
    }
  }
})

function nextStep() {
  if (step.value === 1) {
    if (formData.value.type === 'camera' && !formData.value.connection_id) {
    }
    step.value = 2
  } else if (step.value === 2) {
    step.value = 3
  }
}

async function handleSave() {
  loading.value = true
  error.value = null
  try {
    const data = {
      ...formData.value,
      entity_config: formData.value.entity_config || {}
    }

    if (props.component) {
      await store.update(props.component.id, data)
    } else {
      const created = await store.create(data)
      emit('created', created)
    }
    emit('close')
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Failed to save component'
  } finally {
    loading.value = false
  }
}

function onEntitySelect(entity: any) {
  formData.value.name = formData.value.name || entity.name
  formData.value.entity_config.entity_id = entity.id
  handleSave()
}
</script>

<template>
  <BaseModal
    :show="show"
    :title="component ? 'Edit Component' : 'Add Component'"
    @close="emit('close')"
  >
    <div :class="$style.steps">
      <div :class="[$style.step, { [$style.stepActive]: step === 1 }]">1. Type</div>
      <div :class="[$style.step, { [$style.stepActive]: step === 2 }]">2. Connection</div>
      <div :class="[$style.step, { [$style.stepActive]: step === 3 }]">3. Config</div>
    </div>

    <div v-if="step === 1" :class="$style.form">
      <label>What type of component are you adding?</label>
      <div :class="$style.typeGrid">
        <button
          v-for="t in ['camera', 'control', 'status']"
          :key="t"
          :class="[$style.typeBtn, { [$style.typeActive]: formData.type === t }]"
          @click="formData.type = t as any; nextStep()"
        >
          <span :class="$style.typeIcon">{{ t === 'camera' ? '📷' : t === 'control' ? '🎮' : '📊' }}</span>
          <span :class="$style.typeName">{{ t }}</span>
        </button>
      </div>
    </div>

    <div v-else-if="step === 2" :class="$style.form">
      <label>Select a connection or choose standalone</label>
      <div :class="$style.connList">
        <button
          v-for="c in connStore.connections"
          :key="c.id"
          :class="[$style.connItem, { [$style.connActive]: formData.connection_id === c.id }]"
          @click="formData.connection_id = c.id; formData.provider = c.provider; nextStep()"
        >
          <strong>{{ c.name }}</strong>
          <Badge variant="neutral" size="sm">{{ c.provider }}</Badge>
        </button>

        <div :class="$style.divider">OR</div>

        <button
          :class="[$style.connItem, { [$style.connActive]: !formData.connection_id && formData.provider === 'webrtc' }]"
          @click="formData.connection_id = undefined; formData.provider = 'webrtc'; nextStep()"
        >
          <strong>Standalone WebRTC</strong>
          <span>Direct stream link</span>
        </button>
        <button
          :class="[$style.connItem, { [$style.connActive]: !formData.connection_id && formData.provider === 'webcam' }]"
          @click="formData.connection_id = undefined; formData.provider = 'webcam'; nextStep()"
        >
          <strong>Standalone Webcam</strong>
          <span>Browser or RTSP</span>
        </button>
      </div>
    </div>

    <div v-else-if="step === 3" class="base-form">
      <div class="form-field">
        <label for="component-name">Component Name*</label>
        <Input
          id="component-name"
          v-model="formData.name"
          placeholder="e.g. Front Camera"
          required
          :error="!!error"
        />
      </div>

      <div v-if="formData.connection_id" class="form-field">
        <label>Select Entity from {{ selectedConnection?.name }}</label>
        <EntityBrowser
          :connectionId="formData.connection_id"
          :type="formData.type"
          @select="onEntitySelect"
        />
      </div>

      <ProviderForm
        v-else
        :provider="formData.provider"
        v-model="formData.entity_config"
        mode="entity"
      />

      <div v-if="error" class="form-error">{{ error }}</div>
    </div>

    <template #footer>
      <Button variant="ghost" @click="emit('close')">Cancel</Button>
      <Button v-if="step > 1" variant="secondary" @click="step--">Back</Button>
      <Button
        v-if="step === 3"
        variant="primary"
        @click="handleSave"
        :loading="loading"
      >
        {{ loading ? 'Saving...' : 'Save Component' }}
      </Button>
    </template>
  </BaseModal>
</template>

<style module>
.steps {
  display: flex;
  gap: var(--space-4);
  margin-bottom: var(--space-8);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--border-subtle);
}

.step {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-tertiary);
}

.stepActive {
  color: var(--primary);
}

.form {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.form label {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
}

.typeGrid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-4);
}

.typeBtn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-6);
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-xl);
  transition: all var(--transition-fast);
  cursor: pointer;
}

.typeBtn:hover {
  border-color: var(--border-strong);
  background-color: var(--bg-tertiary);
}

.typeActive {
  border-color: var(--primary);
  background-color: var(--primary-50);
}

.typeIcon {
  font-size: 2rem;
}

.typeName {
  font-weight: var(--font-weight-semibold);
  text-transform: capitalize;
  color: var(--text-primary);
}

.connList {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.connItem {
  padding: var(--space-4);
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: all var(--transition-fast);
  cursor: pointer;
}

.connItem:hover {
  border-color: var(--border-strong);
  background-color: var(--bg-tertiary);
}

.connItem strong {
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}

.connItem span {
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
}

.connActive {
  border-color: var(--primary);
  background-color: var(--primary-50);
}

.divider {
  text-align: center;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-bold);
  color: var(--text-tertiary);
  margin: var(--space-2) 0;
  letter-spacing: var(--letter-spacing-wide);
}
</style>
