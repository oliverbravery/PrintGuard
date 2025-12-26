<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import LiveFeed from './LiveFeed.vue'
import { usePrintersStore } from '../../store/printers'
import { streamsApi } from '../../services/api'
import IconButton from '../ui/IconButton.vue'
import Badge from '../ui/Badge.vue'
import { Play, Pause, Square, Settings, Trash2 } from 'lucide-vue-next'
import type { Printer } from '../../types'

const props = defineProps<{
  printer: Printer
}>()

const emit = defineEmits<{
  (e: 'edit', printer: Printer): void
}>()

const store = usePrintersStore()
const prediction = ref<any>(null)
let pollTimer: any = null

async function pollResults() {
  try {
    const response = await streamsApi.result(props.printer.id)
    prediction.value = response.data
  } catch (e) {
    // Silently fail polling
  }
}

onMounted(() => {
  pollTimer = setInterval(pollResults, 2000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

async function sendCmd(cmd: string) {
  try {
    await store.sendCommand(props.printer.id, cmd)
  } catch (e) {
    alert(`Failed to send ${cmd} command`)
  }
}

async function handleDelete() {
  if (confirm(`Are you sure you want to delete printer "${props.printer.name}"?`)) {
    try {
      await store.remove(props.printer.id)
    } catch (e) {
      alert('Failed to delete printer')
    }
  }
}
</script>

<template>
  <div :class="$style.card">
    <div :class="$style.header">
      <div :class="$style.titleInfo">
        <h3 :class="$style.name">{{ printer.name }}</h3>
        <Badge
          :variant="printer.status === 'printing' ? 'success' : printer.status === 'paused' ? 'warning' : printer.status === 'error' ? 'danger' : 'neutral'"
          size="sm"
        >
          {{ printer.status }}
        </Badge>
      </div>
      <div v-if="prediction && prediction.status === 'success'" :class="[$style.inference, $style[prediction.class_name]]">
        <span :class="$style.icon">{{ prediction.class_name === 'defect' ? '⚠️' : '✅' }}</span>
        <span :class="$style.text">{{ prediction.class_name === 'defect' ? 'DEFECT' : 'NORMAL' }}</span>
        <span :class="$style.confidence">{{ (prediction.confidence * 100).toFixed(0) }}%</span>
      </div>
    </div>

    <div :class="$style.feedWrapper">
      <LiveFeed :printerId="printer.id" :camera="printer.components?.camera" />
    </div>

    <div :class="$style.footer">
      <div :class="$style.controls">
        <IconButton
          variant="default"
          size="sm"
          title="Start"
          :disabled="!printer.has_control || printer.status === 'printing'"
          @click="sendCmd('start')"
        >
          <Play :size="16" />
        </IconButton>
        <IconButton
          variant="default"
          size="sm"
          title="Pause"
          :disabled="!printer.has_control || printer.status !== 'printing'"
          @click="sendCmd('pause')"
        >
          <Pause :size="16" />
        </IconButton>
        <IconButton
          variant="danger"
          size="sm"
          title="Stop"
          :disabled="!printer.has_control || printer.status === 'idle'"
          @click="sendCmd('stop')"
        >
          <Square :size="16" />
        </IconButton>
      </div>

      <div :class="$style.cardActions">
        <IconButton
          variant="ghost"
          size="sm"
          title="Edit Printer"
          @click="emit('edit', printer)"
        >
          <Settings :size="16" />
        </IconButton>
        <IconButton
          variant="danger"
          size="sm"
          title="Delete Printer"
          @click="handleDelete"
        >
          <Trash2 :size="16" />
        </IconButton>
      </div>
    </div>
  </div>
</template>

<style module>
.card {
  background-color: var(--card-bg);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-2xl);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-md);
  transition: all var(--transition-base);
  height: auto;
}

.card:hover {
  box-shadow: var(--shadow-lg);
}

.header {
  padding: var(--space-4);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  height: 80px;
}

.titleInfo {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  flex: 1;
  overflow: hidden;
}

.name {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-bold);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.inference {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-lg);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-extrabold);
  letter-spacing: var(--letter-spacing-wide);
  text-transform: uppercase;
  flex-shrink: 0;
}

.inference.normal {
  background-color: var(--success-bg);
  color: var(--success);
}

.inference.defect {
  background-color: var(--danger-bg);
  color: var(--danger);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0% { opacity: 1; }
  50% { opacity: 0.7; }
  100% { opacity: 1; }
}

.inference .icon {
  font-size: 1rem;
}

.inference .text {
  font-weight: var(--font-weight-extrabold);
}

.inference .confidence {
  font-weight: var(--font-weight-normal);
  opacity: 0.8;
}

.feedWrapper {
  border-top: 1px solid var(--border-subtle);
  border-bottom: 1px solid var(--border-subtle);
  aspect-ratio: 16 / 9;
  background-color: #000;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.footer {
  padding: var(--space-4);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  height: 64px;
}

.controls {
  display: flex;
  gap: var(--space-2);
}

.cardActions {
  display: flex;
  gap: var(--space-2);
}
</style>
