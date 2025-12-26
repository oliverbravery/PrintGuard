<script setup lang="ts">
import { ref, onMounted, watch, computed, nextTick } from 'vue'
import { printersApi } from '../../services/api'
import { useDevices } from '../../composables/useDevices'
import Select from '../ui/Select.vue'
import Input from '../ui/Input.vue'
import type { ProviderSchema, ProviderField } from '../../types'

const props = defineProps<{
  provider: string
  modelValue: Record<string, any>
  mode: 'connection' | 'entity'
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: Record<string, any>): void
}>()

const schema = ref<ProviderSchema | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const videoRef = ref<HTMLVideoElement | null>(null)

const { devices, currentStream, startPreview, stopPreview } = useDevices()

const deviceOptions = computed(() => [
  { value: '', label: 'Select a camera...' },
  ...devices.value.map(d => ({
    value: d.deviceId,
    label: d.label || `Camera ${d.deviceId.slice(0, 5)}`
  }))
])

async function fetchSchema() {
  if (!props.provider) return
  loading.value = true
  error.value = null
  try {
    const response = await printersApi.providerSchema(props.provider)
    schema.value = response.data
    
    const fields = props.mode === 'connection' ? response.data.connection_fields : response.data.entity_fields
    const updates = { ...props.modelValue }
    let changed = false
    
    fields.forEach(f => {
      if (f.type === 'select' && f.options && f.options.length > 0 && updates[f.name] === undefined) {
        updates[f.name] = f.options[0].value
        changed = true
      }
    })
    
    if (changed) {
      emit('update:modelValue', updates)
    }
  } catch (e) {
    error.value = 'Failed to load configuration fields'
  } finally {
    loading.value = false
  }
}

onMounted(fetchSchema)
watch(() => props.provider, fetchSchema)

function updateField(name: string, value: any) {
  emit('update:modelValue', { ...props.modelValue, [name]: value })
}

function checkCondition(condition?: string): boolean {
  if (!condition) return true
  const match = condition.match(/^(\w+)\s*([=!]=)\s*['"]([^'"]+)['"]$/)
  if (!match) return true
  
  const [_, key, op, val] = match
  const currentVal = props.modelValue[key]
  
  if (op === '==') return currentVal === val
  if (op === '!=') return currentVal !== val
  
  return true
}

const visibleFields = computed(() => {
  if (!schema.value) return []
  const fields = props.mode === 'connection' ? schema.value.connection_fields : schema.value.entity_fields
  return fields.filter(f => checkCondition(f.condition))
})

watch(() => props.modelValue.device_id, (newId) => {
  if (newId) {
    startPreview(newId)
  } else {
    stopPreview()
  }
})

watch(currentStream, async (stream) => {
  if (stream) {
    await nextTick()
    
    const el = Array.isArray(videoRef.value) ? videoRef.value[0] : videoRef.value
    
    if (el && typeof el.play === 'function') {
      el.srcObject = stream
      try {
        await el.play()
      } catch (e) {
        console.error('Failed to play video preview:', e)
      }
    } else {
      console.warn('Video element or play method not found', el)
    }
  }
})
</script>

<template>
  <div :class="$style.form">
    <div v-if="loading" :class="$style.loading">Loading configuration...</div>
    <div v-else-if="error" :class="$style.error">{{ error }}</div>
    <div v-else-if="schema">
      <div v-for="field in visibleFields" 
           :key="field.name" 
           class="form-field">
        <label :for="field.name">{{ field.label }}<span v-if="field.required" :class="$style.required">*</span></label>
        
        <!-- Standard Select -->
        <Select 
          v-if="field.type === 'select'"
          :id="field.name"
          :modelValue="modelValue[field.name]"
          :options="field.options || []"
          @update:modelValue="updateField(field.name, $event)"
          fullWidth
        />

        <!-- Device Select for Webcams -->
        <div v-else-if="field.type === 'device_select'" :class="$style.devicePicker">
          <Select 
            :id="field.name"
            :modelValue="modelValue[field.name]"
            :options="deviceOptions"
            @update:modelValue="updateField(field.name, $event)"
            fullWidth
          />
          
          <div v-if="currentStream" :class="$style.preview">
            <video ref="videoRef" autoplay playsinline muted :class="$style.video"></video>
            <div :class="$style.previewBadge">Live Preview</div>
          </div>
        </div>

        <!-- Text/Password Inputs -->
        <Input 
          v-else
          :id="field.name"
          :type="field.type === 'password' ? 'password' : 'text'"
          :modelValue="modelValue[field.name]"
          @update:modelValue="updateField(field.name, $event)"
          :placeholder="field.placeholder || `Enter ${field.label.toLowerCase()}...`"
          fullWidth
        />
      </div>
    </div>
  </div>
</template>

<style module>
.form {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.required {
  color: var(--danger);
  margin-left: var(--space-1);
}

.loading, .error {
  padding: var(--space-8);
  text-align: center;
  color: var(--text-tertiary);
  background-color: var(--bg-secondary);
  border-radius: var(--radius-lg);
  border: 1px dashed var(--border-default);
}

.error {
  color: var(--danger);
  border-color: var(--danger-200);
}

.devicePicker {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.preview {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background-color: #000;
  border-radius: var(--radius-lg);
  overflow: hidden;
  border: 1px solid var(--border-subtle);
}

.video {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.previewBadge {
  position: absolute;
  top: var(--space-3);
  left: var(--space-3);
  background-color: var(--primary);
  color: var(--primary-on);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-bold);
  text-transform: uppercase;
}
</style>

