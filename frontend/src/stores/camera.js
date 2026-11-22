import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'

const DESCRIPTIONS = {
  disconnected: 'Camera not connected',
  connecting: 'Connecting...',
  idle: 'Ready',
  liveview: 'Live View active',
  capturing: 'Capturing...',
  recording: 'Recording video...',
  bulb: 'Bulb exposure...',
  busy: 'Processing...',
  error: 'Error - check connection',
}

export const useCameraStore = defineStore('camera', () => {
  const state = ref('disconnected')
  const connected = ref(false)
  const model = ref(null)
  const serial = ref(null)
  const leasedBy = ref(null)
  const connectedAt = ref(null)
  const lastActivity = ref(null)
  const statusError = ref(null) // camera-reported last_error
  const battery = ref(null) // {level, percent}
  const storage = ref(null) // {cards: []}
  const lastError = ref(null)

  const stateDescription = computed(() => DESCRIPTIONS[state.value] || 'Unknown')
  const isReady = computed(() => connected.value && state.value === 'idle')

  function reset() {
    state.value = 'disconnected'
    connected.value = false
    model.value = serial.value = leasedBy.value = connectedAt.value = null
    lastActivity.value = statusError.value = null
    battery.value = storage.value = null
  }

  function applyStatus(s) {
    if (!s.connected) return reset()
    state.value = s.state
    connected.value = true
    model.value = s.model ?? null
    serial.value = s.serial ?? null
    leasedBy.value = s.leased_by ?? null
    connectedAt.value = s.connected_at ?? null
    lastActivity.value = s.last_activity ?? null
    statusError.value = s.last_error ?? null
  }

  async function fetchStatus() {
    return guard(lastError, async () => {
      const s = await api.getCamera()
      applyStatus(s)
      return s
    })
  }
  async function connect() {
    return guard(lastError, async () => {
      const s = await api.connectCamera()
      applyStatus(s)
      return s
    })
  }
  async function disconnect() {
    return guard(lastError, async () => {
      const s = await api.disconnectCamera()
      applyStatus(s)
      return s
    })
  }
  async function fetchBattery() {
    return guard(lastError, async () => (battery.value = await api.getCameraBattery()))
  }
  async function fetchStorage() {
    return guard(lastError, async () => (storage.value = await api.getCameraStorage()))
  }

  // --- event handlers (called by stores/events.js)
  function onCameraState({ state: next, connected: isConnected }) {
    if (next === 'disconnected') return reset()
    state.value = next
    connected.value = isConnected ?? next !== 'connecting'
  }
  function onConnected({ model: m, serial: s }) {
    connected.value = true
    if (state.value === 'disconnected') state.value = 'idle'
    model.value = m ?? null
    serial.value = s ?? null
  }
  function onBattery({ level }) {
    battery.value = { ...(battery.value || {}), level, percent: battery.value?.percent ?? null }
  }

  return {
    state,
    connected,
    model,
    serial,
    leasedBy,
    connectedAt,
    lastActivity,
    statusError,
    battery,
    storage,
    lastError,
    stateDescription,
    isReady,
    reset,
    applyStatus,
    fetchStatus,
    connect,
    disconnect,
    fetchBattery,
    fetchStorage,
    onCameraState,
    onConnected,
    onDisconnected: reset,
    onBattery,
  }
})
