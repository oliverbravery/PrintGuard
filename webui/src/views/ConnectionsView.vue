<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useConnectionsStore } from '../store/connections'
import { connectionsApi } from '../services/api'
import ConnectionTable from '../components/connections/ConnectionTable.vue'
import ConnectionModal from '../components/connections/ConnectionModal.vue'
import DeleteConfirmModal from '../components/shared/DeleteConfirmModal.vue'
import ConnectionError from '../components/shared/ConnectionError.vue'
import Button from '../components/ui/Button.vue'
import type { Connection, Component } from '../types'

const store = useConnectionsStore()
const showModal = ref(false)
const showDeleteConfirm = ref(false)
const selectedConnection = ref<Connection | null>(null)
const usageComponents = ref<Component[]>([])
const loadingUsage = ref(false)

onMounted(() => {
  store.fetchAll()
})

watch(selectedConnection, async (conn) => {
  if (conn && showDeleteConfirm.value) {
    loadingUsage.value = true
    try {
      const response = await connectionsApi.components(conn.id)
      usageComponents.value = response.data
    } catch (e) {
      console.error(e)
    } finally {
      loadingUsage.value = false
    }
  }
})

function openAdd() {
  selectedConnection.value = null
  showModal.value = true
}

function openEdit(conn: Connection) {
  selectedConnection.value = conn
  showModal.value = true
}

function openDelete(conn: Connection) {
  selectedConnection.value = conn
  showDeleteConfirm.value = true
}

async function confirmDelete(cascade: boolean) {
  if (!selectedConnection.value) return
  try {
    await store.remove(selectedConnection.value.id, cascade)
    showDeleteConfirm.value = false
  } catch (e) {
    console.error(e)
  }
}

function openBrowse(conn: Connection) {
  console.log('Browse entities for:', conn.name)
}
</script>

<template>
  <div class="page-view">
    <header class="page-header">
      <div>
        <h1>Connections</h1>
        <p class="page-subtitle">Manage integrations with HomeAssistant, OctoPrint, and BambuLabs.</p>
      </div>
      <Button variant="primary" @click="openAdd">+ Add Connection</Button>
    </header>

    <div v-if="store.loading && store.connections.length === 0" class="loading-state">Loading connections...</div>

    <ConnectionError
      v-else-if="store.error"
      :message="store.error"
      :loading="store.loading"
      @retry="store.fetchAll()"
    />

    <ConnectionTable
      v-else
      :connections="store.connections"
      @edit="openEdit"
      @delete="openDelete"
      @browse="openBrowse"
    />

    <ConnectionModal
      :show="showModal"
      :connection="selectedConnection"
      @close="showModal = false"
    />

    <DeleteConfirmModal
      v-if="selectedConnection"
      :show="showDeleteConfirm"
      title="Confirm Delete"
      :itemName="selectedConnection.name"
      itemType="connection"
      :usageItems="usageComponents"
      usageLabel="This connection is used by several components:"
      cascadeLabel="Also delete all dependent components"
      :loading="loadingUsage"
      @confirm="confirmDelete"
      @close="showDeleteConfirm = false"
    >
      <template #usage="{ items }">
        <li v-for="c in items" :key="c.id">{{ c.name }} ({{ c.type }})</li>
      </template>
    </DeleteConfirmModal>
  </div>
</template>

<style module>
</style>
