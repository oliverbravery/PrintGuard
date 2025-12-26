import { ref, onMounted, onUnmounted } from 'vue'

export function useDevices() {
  const devices = ref<MediaDeviceInfo[]>([])
  const currentStream = ref<MediaStream | null>(null)
  const error = ref<string | null>(null)

  async function fetchDevices() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true })
      stream.getTracks().forEach(track => track.stop())
      const allDevices = await navigator.mediaDevices.enumerateDevices()
      devices.value = allDevices.filter(d => d.kind === 'videoinput')
    } catch (e: any) {
      error.value = 'Permission denied or no camera found'
      console.error('Error fetching devices:', e)
    }
  }

  async function startPreview(deviceId: string) {
    stopPreview()
    try {
      currentStream.value = await navigator.mediaDevices.getUserMedia({
        video: { deviceId: { ideal: deviceId } }
      })
      error.value = null
    } catch (e: any) {
      error.value = 'Failed to start camera preview'
      console.error('Error starting preview:', e)
    }
  }

  function stopPreview() {
    if (currentStream.value) {
      currentStream.value.getTracks().forEach(track => track.stop())
      currentStream.value = null
    }
  }

  onMounted(fetchDevices)
  onUnmounted(stopPreview)

  return {
    devices,
    currentStream,
    error,
    fetchDevices,
    startPreview,
    stopPreview
  }
}

