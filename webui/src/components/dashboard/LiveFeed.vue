<script setup lang="ts">
import { ref, watch } from 'vue'
import { useWebRTC } from '../../composables/useWebRTC'
import CameraFeed from '../shared/CameraFeed.vue'
import type { ComponentInfo, Component } from '../../types'

const props = defineProps<{
  printerId: string
  camera?: ComponentInfo
}>()

const { push } = useWebRTC()

async function handleStreamReady(stream: MediaStream) {
  if (props.camera) {
    await push(props.printerId, stream, `${props.camera.name || 'Camera'} (Browser)`, props.printerId)
  }
}
</script>

<template>
  <div :class="$style.feed">
    <CameraFeed 
      v-if="camera" 
      :component="(camera as unknown as Component)" 
      :printerId="printerId"
      @stream-ready="handleStreamReady"
    />
    <div v-else :class="$style.placeholder">
      No camera configured
    </div>
  </div>
</template>

<style module>
.feed {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: inherit;
  background-color: #000;
  overflow: hidden;
}

.placeholder {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  font-size: var(--font-size-sm);
}
</style>

