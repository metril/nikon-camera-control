import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useCameraStore = defineStore('camera', () => {
  // Connection state
  const connected = ref(false)
  const state = ref('DISCONNECTED')
  const model = ref(null)
  const serial = ref(null)
  const batteryLevel = ref(null)
  const lastActivity = ref(null)

  // Settings
  const settings = ref({})
  const settingsLoading = ref(false)

  // Live view
  const liveViewActive = ref(false)
  const liveViewFps = ref(0)

  // Capture
  const capturing = ref(false)
  const lastCapture = ref(null)

  // Errors
  const error = ref(null)

  // Computed
  const stateDescription = computed(() => {
    const descriptions = {
      'DISCONNECTED': 'Camera not connected',
      'IDLE': 'Ready',
      'LIVEVIEW': 'Live View active',
      'CAPTURING': 'Capturing photo...',
      'RECORDING': 'Recording video...',
      'BUSY': 'Processing...',
      'ERROR': 'Error - check connection',
    }
    return descriptions[state.value] || 'Unknown'
  })

  const isReady = computed(() => {
    return connected.value && state.value === 'IDLE'
  })

  // Actions
  async function fetchBattery() {
    try {
      const response = await fetch('/api/settings/battery/level')
      if (response.ok) {
        const data = await response.json()
        batteryLevel.value = data.battery_level ?? null
      }
    } catch (e) {
      batteryLevel.value = null
    }
  }

  async function fetchStatus() {
    try {
      const response = await fetch('/api/camera/status')
      if (response.ok) {
        const data = await response.json()
        connected.value = data.connected
        state.value = data.state
        model.value = data.model
        serial.value = data.serial
        lastActivity.value = data.last_activity
        error.value = null
        if (data.connected) fetchBattery()
      }
    } catch (e) {
      error.value = e.message
    }
  }

  async function connect() {
    try {
      error.value = null
      const response = await fetch('/api/camera/connect', { method: 'POST' })
      if (response.ok) {
        const data = await response.json()
        connected.value = data.connected
        state.value = data.state
        model.value = data.model
        serial.value = data.serial
        if (data.connected) fetchBattery()
        return true
      } else {
        const err = await response.json()
        error.value = err.detail || 'Connection failed'
        return false
      }
    } catch (e) {
      error.value = e.message
      return false
    }
  }

  async function disconnect() {
    try {
      const response = await fetch('/api/camera/disconnect', { method: 'POST' })
      if (response.ok) {
        connected.value = false
        state.value = 'DISCONNECTED'
        model.value = null
        serial.value = null
        batteryLevel.value = null
        liveViewActive.value = false
      }
    } catch (e) {
      error.value = e.message
    }
  }

  async function fetchSettings() {
    if (!connected.value) return

    settingsLoading.value = true
    try {
      const response = await fetch('/api/settings/common')
      if (response.ok) {
        const data = await response.json()
        settings.value = data.settings
      }
    } catch (e) {
      error.value = e.message
    } finally {
      settingsLoading.value = false
    }
  }

  async function setSetting(name, value) {
    try {
      const response = await fetch(`/api/settings/${name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value }),
      })
      if (response.ok) {
        const data = await response.json()
        if (data.setting) {
          settings.value[name] = data.setting
        }
        return true
      } else {
        const err = await response.json()
        error.value = err.detail || 'Failed to set setting'
        return false
      }
    } catch (e) {
      error.value = e.message
      return false
    }
  }

  async function capturePhoto() {
    if (!connected.value || capturing.value) return null

    capturing.value = true
    state.value = 'CAPTURING'

    try {
      const response = await fetch('/api/capture/photo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ download: true }),
      })

      if (response.ok) {
        const data = await response.json()
        lastCapture.value = {
          filename: data.filename,
          path: data.path,
          size: data.size,
          timestamp: new Date().toISOString(),
        }
        return data
      } else {
        const err = await response.json()
        error.value = err.detail || 'Capture failed'
        return null
      }
    } catch (e) {
      error.value = e.message
      return null
    } finally {
      capturing.value = false
      state.value = connected.value ? 'IDLE' : 'DISCONNECTED'
    }
  }

  function updateFromWebSocket(event) {
    if (event.type === 'camera_state') {
      state.value = event.new_state
    } else if (event.type === 'initial_status') {
      connected.value = event.data.connected
      state.value = event.data.state
      model.value = event.data.model
    }
  }

  function clearError() {
    error.value = null
  }

  return {
    // State
    connected,
    state,
    model,
    serial,
    batteryLevel,
    lastActivity,
    settings,
    settingsLoading,
    liveViewActive,
    liveViewFps,
    capturing,
    lastCapture,
    error,

    // Computed
    stateDescription,
    isReady,

    // Actions
    fetchStatus,
    connect,
    disconnect,
    fetchSettings,
    setSetting,
    capturePhoto,
    updateFromWebSocket,
    clearError,
  }
})
