import { ref, onUnmounted } from 'vue'
import { streamsApi } from '../services/api'

export function useWebRTC() {
  const videoRef = ref<HTMLVideoElement | null>(null)
  const connected = ref(false)
  const error = ref<string | null>(null)
  const pc = ref<RTCPeerConnection | null>(null)

  async function connect(sessionId: string) {
    if (pc.value) {
      pc.value.close()
    }

    try {
      connected.value = false
      error.value = null

      pc.value = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
      })

      pc.value.ontrack = async (event) => {
        if (videoRef.value) {
          const el = videoRef.value
          el.srcObject = event.streams[0]
          
          try {
            el.load()
            await el.play()
          } catch (e) {
            console.warn('WebRTC autoplay prevented, will retry on interaction', e)
          }
        }
      }

      pc.value.onconnectionstatechange = () => {
        if (pc.value?.connectionState === 'connected') {
          connected.value = true
        } else if (pc.value?.connectionState === 'failed') {
          error.value = 'WebRTC connection failed'
        }
      }

      pc.value.addTransceiver('video', { direction: 'recvonly' })

      const offer = await pc.value.createOffer()
      await pc.value.setLocalDescription(offer)

      await new Promise<void>((resolve) => {
        if (pc.value?.iceGatheringState === 'complete') {
          resolve()
        } else {
          const checkState = () => {
            if (pc.value?.iceGatheringState === 'complete') {
              pc.value.removeEventListener('icegatheringstatechange', checkState)
              resolve()
            }
          }
          pc.value?.addEventListener('icegatheringstatechange', checkState)
        }
      })

      const response = await streamsApi.view(sessionId, {
        sdp: pc.value?.localDescription?.sdp,
        type: pc.value?.localDescription?.type
      })

      await pc.value.setRemoteDescription(new RTCSessionDescription(response.data))
    } catch (e: any) {
      error.value = e.message || 'Failed to connect'
      console.error('WebRTC error:', e)
    }
  }

  function disconnect() {
    if (pc.value) {
      pc.value.close()
      pc.value = null
    }
    if (videoRef.value) {
      videoRef.value.srcObject = null
    }
    connected.value = false
  }

  onUnmounted(disconnect)

  async function push(sessionId: string, stream: MediaStream, deviceName = 'Webcam', printerId?: string) {
    if (pc.value) {
      pc.value.close()
    }

    try {
      connected.value = false
      error.value = null

      pc.value = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
      })

      stream.getTracks().forEach(track => {
        pc.value?.addTrack(track, stream)
      })

      pc.value.onconnectionstatechange = () => {
        if (pc.value?.connectionState === 'connected') {
          connected.value = true
        } else if (pc.value?.connectionState === 'failed') {
          error.value = 'WebRTC push failed'
        }
      }

      const offer = await pc.value.createOffer()
      await pc.value.setLocalDescription(offer)

      await new Promise<void>((resolve) => {
        if (pc.value?.iceGatheringState === 'complete') {
          resolve()
        } else {
          const checkState = () => {
            if (pc.value?.iceGatheringState === 'complete') {
              pc.value.removeEventListener('icegatheringstatechange', checkState)
              resolve()
            }
          }
          pc.value?.addEventListener('icegatheringstatechange', checkState)
        }
      })

      const response = await streamsApi.offer({
        sdp: pc.value?.localDescription?.sdp,
        type: pc.value?.localDescription?.type,
        session_id: sessionId,
        device_name: deviceName,
        printer_id: printerId
      })

      await pc.value.setRemoteDescription(new RTCSessionDescription(response.data))
    } catch (e: any) {
      error.value = e.message || 'Failed to push stream'
      console.error('WebRTC push error:', e)
    }
  }

  return {
    videoRef,
    connected,
    error,
    connect,
    push,
    disconnect
  }
}

