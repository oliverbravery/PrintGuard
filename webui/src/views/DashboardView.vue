<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { usePrintersStore } from '../store/printers'
import PrinterCard from '../components/dashboard/PrinterCard.vue'
import PrinterModal from '../components/printers/PrinterModal.vue'
import ConnectionError from '../components/shared/ConnectionError.vue'
import Button from '../components/ui/Button.vue'
import { Printer } from '../types'

const store = usePrintersStore()
const showModal = ref(false)
const selectedPrinter = ref<Printer | null>(null)

onMounted(() => {
  store.fetchAll()
})

function openAdd() {
  selectedPrinter.value = null
  showModal.value = true
}

function openEdit(printer: Printer) {
  selectedPrinter.value = printer
  showModal.value = true
}
</script>

<template>
  <div :class="['page-view', $style.view]">
    <header class="page-header">
      <div>
        <h1>Dashboard</h1>
        <p class="page-subtitle">Monitor and control your connected 3D printers.</p>
      </div>
      <Button variant="primary" @click="openAdd">
        + Add Printer
      </Button>
    </header>

    <div v-if="store.loading && store.printers.length === 0" :class="$style.loading">
      <div :class="$style.spinner"></div>
      <span>Fetching printers...</span>
    </div>

    <ConnectionError
      v-else-if="store.error"
      :message="store.error"
      :loading="store.loading"
      @retry="store.fetchAll()"
    />

    <div v-else-if="store.printers.length === 0" :class="$style.empty">
      <div :class="$style.emptyIcon">🖨️</div>
      <h2>No printers setup</h2>
      <p>Click "Add Printer" to start monitoring your first machine.</p>
      <Button :class="$style.addBtnLarge" variant="primary" size="lg" @click="openAdd">
        Add Your First Printer
      </Button>
    </div>

    <div v-else :class="$style.grid">
      <PrinterCard
        v-for="p in store.printers"
        :key="p.id"
        :printer="p"
        @edit="openEdit"
      />
    </div>

    <PrinterModal
      :show="showModal"
      :printer="selectedPrinter"
      @close="showModal = false"
    />
  </div>
</template>

<style module>
.view {
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: var(--space-6);
  align-items: start;
}

.loading, .empty {
  padding: var(--space-16) var(--space-4);
  text-align: center;
  color: var(--text-tertiary);
  background-color: var(--card-bg);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-2xl);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-6);
}

.emptyIcon {
  font-size: 4rem;
  opacity: 0.5;
}

.empty h2 {
  color: var(--text-primary);
  font-size: var(--font-size-xl);
}

.addBtnLarge {
  margin-top: var(--space-4);
}

.spinner {
  width: 3rem;
  height: 3rem;
  border: 4px solid var(--primary-200);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}
</style>
