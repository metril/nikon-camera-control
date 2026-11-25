import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'
import { useStorageStore } from './storage'

const RECENT_LIMIT = 14

export const useCaptureStore = defineStore('capture', () => {
  const lastCapture = ref(null) // CaptureOut from the last blocking capture
  const lastFiles = ref([]) // files from the last capture_complete event
  const inFlight = ref(false)
  const bulbActive = ref(false)
  const recent = ref([]) // newest saved files, for the strip under the live view
  const lastError = ref(null)

  let pendingRequests = 0 // blocking capture() calls awaiting their HTTP response

  /** Blocking capture; body: {download, delete_from_camera, filename_prefix}. */
  async function capture(body = {}) {
    pendingRequests++
    inFlight.value = true
    try {
      return await guard(
        lastError,
        async () => (lastCapture.value = await api.capturePhoto({ body })),
      )
    } finally {
      pendingRequests--
      inFlight.value = false
    }
  }
  const trigger = () => guard(lastError, () => api.triggerCapture())
  /** Returns the job for one bracket set. */
  const bracket = (body) => guard(lastError, () => api.startBracketCapture({ body }))

  /** Newest saved files (Shoot's recent captures). */
  async function loadRecent() {
    if (!useStorageStore().targetId) return recent.value // nothing is saved without a target
    const page = await api.listFiles({
      query: { folder: '', page: 1, limit: RECENT_LIMIT, kind: 'image', sort: 'newest' },
    })
    recent.value = page.items || []
    // the last shot overlay on the live view reads lastFiles: seed it after a reload
    if (!lastFiles.value.length && recent.value.length) lastFiles.value = [recent.value[0]]
    return recent.value
  }

  function onStarted({ bulb }) {
    inFlight.value = true
    bulbActive.value = !!bulb
  }
  function onComplete({ files }) {
    inFlight.value = false
    bulbActive.value = false
    lastFiles.value = files || []
    loadRecent().catch(() => {})
  }

  /** Camera gone or events lost: nothing is in flight any more. */
  function reset() {
    // a long exposure's own request is still running: it clears inFlight when it returns
    if (!pendingRequests) inFlight.value = false
    bulbActive.value = false
  }

  return {
    lastCapture,
    lastFiles,
    inFlight,
    bulbActive,
    recent,
    lastError,
    loadRecent,
    capture,
    trigger,
    bracket,
    onStarted,
    onComplete,
    reset,
  }
})
