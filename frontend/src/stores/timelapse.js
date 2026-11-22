import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'

const EVENT_STATE = {
  timelapse_started: 'running',
  timelapse_paused: 'paused',
  timelapse_resumed: 'running',
  timelapse_stopped: 'stopped',
  timelapse_completed: 'completed',
  timelapse_error: 'failed',
}
const POLL_MS = 15_000

export const useTimelapseStore = defineStore('timelapse', () => {
  const status = ref(null) // TimelapseStatus
  const preview = ref(null)
  const presets = ref(null)
  const progress = ref(null) // latest counters from events
  const lastFrame = ref(null) // latest timelapse_frame payload
  const warning = ref(null)
  const lastError = ref(null)
  let pollTimer = null

  const state = computed(() => status.value?.state ?? 'idle')
  const isActive = computed(() => ['running', 'paused', 'stopping'].includes(state.value))

  const apply = (s) => (status.value = s)
  const fetchStatus = () =>
    guard(lastError, async () => (apply(await api.getTimelapseStatus()), status.value))
  const act = (fn) => guard(lastError, async () => (apply(await fn()), status.value))

  const setConfig = (body) => guard(lastError, () => api.setTimelapseConfig({ body }))
  const fetchPreview = () =>
    guard(lastError, async () => (preview.value = await api.previewTimelapse()))
  const fetchPresets = () =>
    guard(lastError, async () => (presets.value = await api.listTimelapsePresets()))
  const start = () => act(() => api.startTimelapse())
  const pause = () => act(() => api.pauseTimelapse())
  const resume = () => act(() => api.resumeTimelapse())
  const stop = () => act(() => api.stopTimelapse())

  function onEvent(type, data = {}) {
    const next = EVENT_STATE[type]
    if (next && status.value) status.value = { ...status.value, state: next }
    if (type === 'timelapse_frame') lastFrame.value = data
    if (type === 'timelapse_warning') warning.value = data
    if (data.frames_done !== undefined) progress.value = { ...progress.value, ...data }
    if (next) fetchStatus().catch(() => {}) // authoritative refresh; failure is kept in lastError
  }

  /** Slow fallback while a time-lapse is active; skipped while the tab is hidden. */
  function startPolling(ms = POLL_MS) {
    stopPolling()
    pollTimer = setInterval(() => {
      if (document.visibilityState === 'hidden' || !isActive.value) return
      fetchStatus().catch(() => {})
    }, ms)
  }
  function stopPolling() {
    clearInterval(pollTimer)
    pollTimer = null
  }

  return {
    status,
    state,
    isActive,
    preview,
    presets,
    progress,
    lastFrame,
    warning,
    lastError,
    fetchStatus,
    setConfig,
    fetchPreview,
    fetchPresets,
    start,
    pause,
    resume,
    stop,
    onEvent,
    startPolling,
    stopPolling,
  }
})
