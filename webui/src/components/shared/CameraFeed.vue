<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { componentsApi, printersApi } from '../../services/api'
import { useWebRTC } from '../../composables/useWebRTC'
import { useDevices } from '../../composables/useDevices'
import StreamPreview from './StreamPreview.vue'
import type { Component } from '../../types'

const props = defineProps<{
  component: Component | null
  printerId?: string
}>()

const { currentStream, startPreview, stopPreview } = useDevices()
const sessionId = ref<string | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)
const videoRef = ref<HTMLVideoElement | null>(null)

async function initStream() {
  if (!props.component || props.component.type !== 'camera') {
    sessionId.value = null
    error.value = null
    return
  }

  loading.value = true
  error.value = null
  
  try {
    const isBrowserWebcam = props.component.provider === 'webcam' && props.component.entity_config?.type === 'browser'
    
    if (isBrowserWebcam) {
      const deviceId = props.component.entity_config?.device_id
      if (deviceId) {
        await startPreview(deviceId)
      } else {
        error.value = 'No device ID configured'
      }
    } else {
      const id = `stream-${props.component.id}-${Math.random().toString(36).slice(2, 9)}`
      if (props.printerId) {
        await printersApi.stream(props.printerId, id)
      } else {
        await componentsApi.stream(props.component.id, id)
      }
      sessionId.value = id
    }
  } catch (e: any) {
    error.value = e.response?.data?.detail || 'Failed to initialize stream'
    console.error('CameraFeed error:', e)
  } finally {
    loading.value = false
  }
}

function cleanup() {
  stopPreview()
  sessionId.value = null
}

onMounted(initStream)
onUnmounted(cleanup)

watch(() => props.component?.id, (newId, oldId) => {
  if (newId !== oldId) {
    cleanup()
    initStream()
  }
})

const emit = defineEmits<{
  (e: 'stream-ready', stream: MediaStream): void
}>()

watch(currentStream, async (stream) => {
  if (stream && props.component?.provider === 'webcam' && props.component?.entity_config?.type === 'browser') {
    await nextTick()
    if (videoRef.value) {
      videoRef.value.srcObject = stream
      videoRef.value.play().catch(console.error)
    }
    emit('stream-ready', stream)
  }
})
</script>

<template>
  <div :class="$style.feed">
    <div v-if="loading && !sessionId && !currentStream" :class="$style.overlay">
      <div :class="$style.spinner"></div>
      <span>Initializing...</span>
    </div>
    
    <div v-else-if="error" :class="$style.overlay">
      <span :class="$style.errorText">{{ error }}</span>
      <button :class="$style.retryBtn" @click="initStream">Retry</button>
    </div>
    
    <div v-else :class="$style.content">
      <!-- Browser Webcam -->
      <video 
        v-if="component?.provider === 'webcam' && component?.entity_config?.type === 'browser'"
        ref="videoRef"
        autoplay 
        playsinline 
        muted 
        :class="$style.video"
      ></video>
      
      <!-- Remote Stream -->
      <StreamPreview 
        v-else-if="sessionId" 
        :sessionId="sessionId" 
        :class="$style.stream"
      />
      
      <div v-else :class="$style.placeholder">
        No camera selected
      </div>
    </div>
  </div>
</template>

<style module>
.feed {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background-color: #000;
  overflow: hidden;
}

.content {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.video, .stream {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.overlay, .placeholder {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background-color: rgba(0, 0, 0, 0.5);
  color: white;
  gap: var(--space-4);
  font-size: var(--font-size-sm);
}

.errorText {
  color: var(--danger-400);
  text-align: center;
  padding: 0 var(--space-4);
}

.retryBtn {
  padding: var(--space-1) var(--space-3);
  background-color: var(--primary);
  border-radius: var(--radius-md);
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-xs);
  color: white;
}

.spinner {
  width: 1.5rem;
  height: 1.5rem;
  border: 2px solid rgba(255, 255, 255, 0.2);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>

