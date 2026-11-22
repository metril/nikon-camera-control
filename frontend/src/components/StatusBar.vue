<script setup>
import { ref, computed } from 'vue'
import { useCameraStore } from '../stores/camera'

const camera = useCameraStore()
const isConnecting = ref(false)

const statusColor = computed(() => {
  if (camera.connected) return 'bg-camera-success'
  if (camera.error) return 'bg-camera-error'
  return 'bg-camera-muted'
})

const statusText = computed(() => {
  if (isConnecting.value) return 'Connecting...'
  if (camera.connected) return camera.model || 'Connected'
  if (camera.error) return camera.error
  return 'Disconnected'
})

const stateText = computed(() => {
  switch (camera.state) {
    case 'IDLE': return 'Ready'
    case 'LIVEVIEW': return 'Live View'
    case 'CAPTURING': return 'Capturing'
    case 'RECORDING': return 'Recording'
    case 'BUSY': return 'Busy'
    case 'ERROR': return 'Error'
    default: return ''
  }
})

async function toggleConnection() {
  if (camera.connected) {
    await camera.disconnect()
  } else {
    isConnecting.value = true
    try {
      await camera.connect()
    } finally {
      isConnecting.value = false
    }
  }
}
</script>

<template>
  <div class="bg-camera-surface border border-camera-border rounded-lg px-4 py-3">
    <div class="flex items-center justify-between">
      <!-- Connection Status -->
      <div class="flex items-center gap-3">
        <div class="flex items-center gap-2">
          <span
            class="w-2.5 h-2.5 rounded-full"
            :class="statusColor"
          ></span>
          <span class="font-medium">{{ statusText }}</span>
        </div>

        <!-- Camera State Badge -->
        <span
          v-if="camera.connected && stateText"
          class="px-2 py-0.5 text-xs rounded bg-camera-border text-camera-muted"
        >
          {{ stateText }}
        </span>
      </div>

      <!-- Right Side: Connection Button & Info -->
      <div class="flex items-center gap-4">
        <!-- Quick Stats (when connected) -->
        <div v-if="camera.connected" class="hidden sm:flex items-center gap-4 text-sm text-camera-muted">
          <div v-if="camera.batteryLevel != null" class="flex items-center gap-1">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8V6a2 2 0 00-2-2H9a2 2 0 00-2 2v2M17 8v10a2 2 0 01-2 2H9a2 2 0 01-2-2V8m10 0H7m5 4v4" />
            </svg>
            <span>{{ camera.batteryLevel }}%</span>
          </div>

          <div v-if="camera.liveViewActive" class="flex items-center gap-1 text-camera-success">
            <span class="w-2 h-2 bg-camera-success rounded-full recording-dot"></span>
            <span>Live</span>
          </div>
        </div>

        <!-- Connect/Disconnect Button -->
        <button
          @click="toggleConnection"
          :disabled="isConnecting"
          class="px-4 py-1.5 text-sm font-medium rounded transition-colors"
          :class="camera.connected
            ? 'bg-camera-border text-camera-text hover:bg-camera-border/80'
            : 'bg-camera-accent text-white hover:bg-camera-accent/80'"
        >
          <span v-if="isConnecting" class="flex items-center gap-2">
            <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            Connecting
          </span>
          <span v-else>
            {{ camera.connected ? 'Disconnect' : 'Connect' }}
          </span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.recording-dot {
  animation: pulse-dot 1.5s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
