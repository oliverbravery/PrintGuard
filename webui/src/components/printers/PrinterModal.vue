<script setup lang="ts">
import { ref, watch } from 'vue'
import BaseModal from '../shared/BaseModal.vue'
import ComponentSelector from '../shared/ComponentSelector.vue'
import ComponentModal from '../library/ComponentModal.vue'
import Button from '../ui/Button.vue'
import Input from '../ui/Input.vue'
import { usePrintersStore } from '../../store/printers'
import { useComponentsStore } from '../../store/components'
import type { Printer, PrinterCreate } from '../../types'

const props = defineProps<{
  show: boolean
  printer?: Printer | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const store = usePrintersStore()
const compStore = useComponentsStore()
const loading = ref(false)
const error = ref<string | null>(null)

const showCompModal = ref(false)
const activeCompType = ref<'camera' | 'control' | 'status'>('camera')

const formData = ref<PrinterCreate>({
  name: '',
  components: {
    camera: '',
    status: null,
    control: null
  }
})

watch([() => props.show, () => props.printer], ([show, printer]) => {
  if (show) {
    compStore.fetchAll()

    if (printer) {
      const comps = printer.components || {}
      formData.value = {
        name: printer.name,
        components: {
          camera: comps.camera?.id || '',
          status: comps.status?.id || null,
          control: comps.control?.id || null
        }
      }
    } else {
      formData.value = {
        name: '',
        components: {
          camera: '',
          status: null,
          control: null
        }
      }
    }
  }
}, { immediate: true })

function openAddNew(type: 'camera' | 'control' | 'status') {
  activeCompType.value = type
  showCompModal.value = true
}

function onComponentCreated(comp: any) {
  if (comp.type === 'camera') formData.value.components.camera = comp.id
  else if (comp.type === 'status') formData.value.components.status = comp.id
  else if (comp.type === 'control') formData.value.components.control = comp.id

  showCompModal.value = false
}

async function handleSave() {
  if (!formData.value.components.camera) {
    error.value = 'Camera is required'
    return
  }

  loading.value = true
  error.value = null
  try {
    if (props.printer) {
      await store.update(props.printer.id, formData.value)
    } else {
      await store.create(formData.value)
    }
    emit('close')
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Failed to save printer'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <BaseModal
    :show="show"
    :title="printer ? 'Edit Printer' : 'Add Printer'"
    @close="emit('close')"
  >
    <form @submit.prevent="handleSave" class="base-form">
      <div class="form-field">
        <label for="printer-name">Printer Name*</label>
        <Input
          id="printer-name"
          v-model="formData.name"
          placeholder="e.g. Ender 3 V2"
          required
          :error="!!error"
        />
      </div>

      <div class="form-field">
        <label>Camera Source* (Required)</label>
        <ComponentSelector
          type="camera"
          v-model="formData.components.camera"
          required
          @add-new="openAddNew('camera')"
        />
      </div>

      <div class="form-field">
        <label>Status Source (Optional)</label>
        <ComponentSelector
          type="status"
          v-model="formData.components.status"
          @add-new="openAddNew('status')"
          placeholder="No status source selected"
        />
      </div>

      <div class="form-field">
        <label>Control Source (Optional)</label>
        <ComponentSelector
          type="control"
          v-model="formData.components.control"
          @add-new="openAddNew('control')"
          placeholder="No control source selected"
        />
      </div>

      <div v-if="error" class="form-error">{{ error }}</div>
    </form>

    <template #footer>
      <Button variant="ghost" @click="emit('close')">Cancel</Button>
      <Button
        variant="primary"
        @click="handleSave"
        :loading="loading"
      >
        {{ loading ? 'Saving...' : 'Save Printer' }}
      </Button>
    </template>

    <ComponentModal
      :show="showCompModal"
      :initialType="activeCompType"
      @close="showCompModal = false"
      @created="onComponentCreated"
    />
  </BaseModal>
</template>

<style module>
</style>
