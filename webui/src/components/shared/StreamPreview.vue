<script setup lang="ts">
import { watch, onMounted } from 'vue'
import { useWebRTC } from '../../composables/useWebRTC'

const props = defineProps<{
  sessionId?: string
}>()

const { videoRef, connected, error, connect, disconnect } = useWebRTC()

watch(() => props.sessionId, (newId) => {
  if (newId) {
    connect(newId)
  } else {
    disconnect()
  }
})

onMounted(() => {
  if (props.sessionId) {
    connect(props.sessionId)
  }
})
</script>

<template>
  <div :class="$style.preview">
    <video 
      ref="videoRef" 
      autoplay 
      playsinline 
      muted 
      :class="[$style.video, { [$style.visible]: connected }]"
    ></video>
    
    <div v-if="!sessionId" :class="$style.placeholder">
      No camera selected
    </div>
    <div v-else-if="error" :class="$style.error">
      {{ error }}
    </div>
    <div v-else-if="!connected" :class="$style.loading">
      <div :class="$style.spinner"></div>
      Connecting to stream...
    </div>
  </div>
</template>

<style module>
.preview {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background-color: #000;
  border-radius: 0.5rem;
  overflow: hidden;
  border: 1px solid var(--border);
}

.video {
  width: 100%;
  height: 100%;
  object-fit: contain;
  opacity: 0;
  transition: opacity 0.3s;
}

.video.visible {
  opacity: 1;
}

.placeholder, .error, .loading {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  gap: 1rem;
}

.error {
  color: var(--danger);
  padding: 1rem;
  text-align: center;
}

.spinner {
  width: 2rem;
  height: 2rem;
  border: 3px solid rgba(59, 130, 246, 0.3);
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
</style>

