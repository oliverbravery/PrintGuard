<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useComponentsStore } from '../store/components'
import { useConnectionsStore } from '../store/connections'
import { componentsApi } from '../services/api'
import ComponentTable from '../components/library/ComponentTable.vue'
import ComponentFilters from '../components/library/ComponentFilters.vue'
import ComponentModal from '../components/library/ComponentModal.vue'
import ComponentPreviewModal from '../components/library/ComponentPreviewModal.vue'
import DeleteConfirmModal from '../components/shared/DeleteConfirmModal.vue'
import ConnectionError from '../components/shared/ConnectionError.vue'
import Button from '../components/ui/Button.vue'
import type { Component } from '../types'

const store = useComponentsStore()
const connStore = useConnectionsStore()
const showModal = ref(false)
const showDeleteConfirm = ref(false)
const showPreviewModal = ref(false)
const selectedComponent = ref<Component | null>(null)
const usagePrinters = ref<any[]>([])
const loadingUsage = ref(false)

onMounted(() => {
  store.fetchAll()
  connStore.fetchAll()
})

watch(selectedComponent, async (comp) => {
  if (comp && showDeleteConfirm.value) {
    loadingUsage.value = true
    try {
      const response = await componentsApi.printers(comp.id)
      usagePrinters.value = response.data
    } catch (e) {
      console.error(e)
    } finally {
      loadingUsage.value = false
    }
  }
})

function onFilterChange(filters: any) {
  store.fetchAll(filters)
}

function openAdd() {
  selectedComponent.value = null
  showModal.value = true
}

function openEdit(comp: Component) {
  selectedComponent.value = comp
  showModal.value = true
}

function openDelete(comp: Component) {
  selectedComponent.value = comp
  showDeleteConfirm.value = true
}

async function confirmDelete(force: boolean) {
  if (!selectedComponent.value) return
  try {
    await store.remove(selectedComponent.value.id, force)
    showDeleteConfirm.value = false
  } catch (e) {
    console.error(e)
  }
}

function openPreview(comp: Component) {
  selectedComponent.value = comp
  showPreviewModal.value = true
}
</script>

<template>
  <div class="page-view">
    <header class="page-header">
      <div>
        <h1>Component Library</h1>
        <p class="page-subtitle">Manage cameras, control sources, and status monitors.</p>
      </div>
      <Button variant="primary" @click="openAdd">+ Add Component</Button>
    </header>

    <ComponentFilters @change="onFilterChange" />

    <div v-if="store.loading && store.components.length === 0" class="loading-state">Loading components...</div>

    <ConnectionError
      v-else-if="store.error"
      :message="store.error"
      :loading="store.loading"
      @retry="store.fetchAll()"
    />

    <ComponentTable
      v-else
      :components="store.components"
      @edit="openEdit"
      @delete="openDelete"
      @preview="openPreview"
    />

    <ComponentModal
      :show="showModal"
      :component="selectedComponent"
      @close="showModal = false"
    />

    <ComponentPreviewModal
      :show="showPreviewModal"
      :component="selectedComponent"
      @close="showPreviewModal = false"
    />

    <DeleteConfirmModal
      v-if="selectedComponent"
      :show="showDeleteConfirm"
      title="Delete Component"
      :itemName="selectedComponent.name"
      itemType="component"
      :usageItems="usagePrinters"
      usageLabel="This component is used by several printers:"
      cascadeLabel="I understand, delete it anyway"
      :loading="loadingUsage"
      @confirm="confirmDelete"
      @close="showDeleteConfirm = false"
    >
      <template #usage="{ items }">
        <li v-for="u in items" :key="u.printer_id">Printer ID: {{ u.printer_id }} (Role: {{ u.role }})</li>
      </template>
    </DeleteConfirmModal>
  </div>
</template>

<style module>
</style>
