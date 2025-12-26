<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { adminApi } from '../../services/api'
import Button from '../ui/Button.vue'
import Input from '../ui/Input.vue'
import Badge from '../ui/Badge.vue'
import MultiSelect from '../ui/MultiSelect.vue'
import { AVAILABLE_SCOPES } from '../../types/scopes'
import type { M2MApplication } from '../../types'

const apps = ref<M2MApplication[]>([])
const loading = ref(false)
const showAdd = ref(false)
const newApp = ref({ name: '', scopes: ['printer:read', 'rtc:stream'] })
const lastCreated = ref<any>(null)

const scopeOptions = AVAILABLE_SCOPES.map(s => ({ value: s, label: s }))

async function fetchApps() {
  loading.value = true
  try {
    const response = await adminApi.listM2M()
    apps.value = response.data
  } finally {
    loading.value = false
  }
}

async function handleAdd() {
  try {
    const response = await adminApi.createM2M({
      ...newApp.value,
      scopes: newApp.value.scopes.join(' ')
    })
    lastCreated.value = response.data
    showAdd.value = false
    newApp.value = { name: '', scopes: ['printer:read', 'rtc:stream'] }
    fetchApps()
  } catch (e) {
    alert('Failed to add M2M app')
  }
}

async function handleDelete(clientId: string) {
  if (!confirm(`Delete M2M application ${clientId}?`)) return
  try {
    await adminApi.deleteM2M(clientId)
    fetchApps()
  } catch (e) {
    alert('Failed to delete M2M app')
  }
}

onMounted(fetchApps)
</script>

<template>
  <div :class="$style.section">
    <div :class="$style.header">
      <h3>M2M Applications</h3>
      <Button variant="ghost" size="sm" @click="showAdd = !showAdd">
        {{ showAdd ? 'Cancel' : '+ New M2M App' }}
      </Button>
    </div>

    <div v-if="lastCreated" :class="$style.secretAlert">
      <h4>⚠️ Save your client secret!</h4>
      <p>It will not be shown again.</p>
      <div :class="$style.secretBox">
        <div><strong>Client ID:</strong> <code>{{ lastCreated.client_id }}</code></div>
        <div><strong>Client Secret:</strong> <code>{{ lastCreated.client_secret }}</code></div>
      </div>
      <Button variant="ghost" size="sm" :class="$style.dismiss" @click="lastCreated = null">Dismiss</Button>
    </div>

    <div v-if="showAdd" :class="$style.addCard">
      <form @submit.prevent="handleAdd" :class="$style.form">
        <Input v-model="newApp.name" placeholder="App Name (e.g. Home Assistant)" required />
        <MultiSelect 
          v-model="newApp.scopes" 
          :options="scopeOptions" 
          placeholder="Select Scopes" 
        />
        <Button type="submit" variant="primary">Create Application</Button>
      </form>
    </div>

    <div class="table-container">
      <table class="base-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Client ID</th>
            <th>Scopes</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="app in apps" :key="app.client_id">
            <td><strong>{{ app.name }}</strong></td>
            <td><code>{{ app.client_id }}</code></td>
            <td>
              <div :class="$style.scopes">
                <Badge v-for="s in app.scopes.split(' ')" :key="s" variant="neutral" size="sm">{{ s }}</Badge>
              </div>
            </td>
            <td>
              <Button variant="danger" size="sm" @click="handleDelete(app.client_id)">Delete</Button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style module>
.section {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.secretAlert {
  background-color: var(--warning-bg);
  border: 1px solid var(--warning-200);
  border-radius: var(--radius-xl);
  padding: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.secretAlert h4 {
  color: var(--warning);
}

.secretBox {
  background-color: var(--bg-secondary);
  padding: var(--space-4);
  border-radius: var(--radius-lg);
  font-family: monospace;
  font-size: var(--font-size-sm);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  border: 1px solid var(--border-subtle);
}

.secretBox code {
  color: var(--text-primary);
  font-weight: var(--font-weight-bold);
}

.dismiss {
  align-self: flex-end;
  color: var(--warning);
}

.addCard {
  background-color: var(--card-bg);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xl);
  padding: var(--space-6);
  box-shadow: var(--shadow-sm);
}

.form {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: var(--space-4);
  align-items: flex-end;
}

.scopes {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}
</style>

