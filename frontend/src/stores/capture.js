import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'

export const useCaptureStore = defineStore('capture', () => {
  const lastCapture = ref(null) // CaptureOut from the last blocking capture
  const lastFiles = ref([]) // files from the last capture_complete event
  const inFlight = ref(false)
  const bulbActive = ref(false)
  const lastError = ref(null)

  /** Blocking capture; body: {download, delete_from_camera, filename_prefix}. */
  async function capture(body = {}) {
    inFlight.value = true
    try {
      return await guard(
        lastError,
        async () => (lastCapture.value = await api.capturePhoto({ body })),
      )
    } finally {
      inFlight.value = false
    }
  }
  const trigger = () => guard(lastError, () => api.triggerCapture())
  /** Returns the job for one bracket set. */
  const bracket = (body) => guard(lastError, () => api.startBracketCapture({ body }))

  function onStarted({ bulb }) {
    inFlight.value = true
    bulbActive.value = !!bulb
  }
  function onComplete({ files }) {
    inFlight.value = false
    bulbActive.value = false
    lastFiles.value = files || []
  }

  return {
    lastCapture,
    lastFiles,
    inFlight,
    bulbActive,
    lastError,
    capture,
    trigger,
    bracket,
    onStarted,
    onComplete,
  }
})
