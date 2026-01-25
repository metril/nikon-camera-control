<script setup>
import { ref, computed } from 'vue'
import { useCameraStore } from '../stores/camera'

const camera = useCameraStore()
const isCapturing = ref(false)
const captureAnimation = ref(false)
const lastCapture = ref(null)

const canCapture = computed(() => {
  return camera.connected && !isCapturing.value && camera.state !== 'CAPTURING'
})

async function capture() {
  if (!canCapture.value) return

  isCapturing.value = true
  captureAnimation.value = true

  try {
    const result = await camera.capturePhoto()
    lastCapture.value = {
      success: true,
      filename: result?.filename || 'Photo captured',
      timestamp: new Date()
    }
  } catch (error) {
    lastCapture.value = {
      success: false,
      error: error.message || 'Capture failed',
      timestamp: new Date()
    }
  } finally {
    isCapturing.value = false
    // Keep animation for a bit longer for visual feedback
    setTimeout(() => {
      captureAnimation.value = false
    }, 300)
  }
}

function formatTime(date) {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

// Expose capture function for keyboard shortcut
defineExpose({ capture })
</script>

<template>
  <div class="bg-camera-surface border border-camera-border rounded-lg p-4">
    <div class="flex flex-col items-center gap-4">
      <!-- Capture Button -->
      <button
        @click="capture"
        :disabled="!canCapture"
        class="relative w-20 h-20 rounded-full transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-camera-accent focus:ring-offset-2 focus:ring-offset-camera-surface"
        :class="[
          canCapture
            ? 'bg-camera-error hover:bg-camera-error/90 active:scale-95'
            : 'bg-camera-muted cursor-not-allowed',
          captureAnimation ? 'scale-90' : ''
        ]"
      >
        <!-- Outer ring -->
        <span class="absolute inset-1 rounded-full border-2 border-white/30"></span>

        <!-- Inner circle -->
        <span
          class="absolute inset-3 rounded-full bg-white/20"
          :class="captureAnimation ? 'animate-ping' : ''"
        ></span>

        <!-- Icon -->
        <span class="absolute inset-0 flex items-center justify-center">
          <svg
            v-if="isCapturing"
            class="w-8 h-8 text-white animate-spin"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <svg
            v-else
            class="w-8 h-8 text-white"
            fill="currentColor"
            viewBox="0 0 24 24"
          >
            <circle cx="12" cy="12" r="8" />
          </svg>
        </span>
      </button>

      <!-- Label -->
      <div class="text-center">
        <p class="text-sm font-medium">
          {{ isCapturing ? 'Capturing...' : 'Capture' }}
        </p>
        <p class="text-xs text-camera-muted">
          Press Space to capture
        </p>
      </div>

      <!-- Last Capture Status -->
      <div
        v-if="lastCapture"
        class="w-full mt-2 p-3 rounded text-sm"
        :class="lastCapture.success ? 'bg-camera-success/10 text-camera-success' : 'bg-camera-error/10 text-camera-error'"
      >
        <div class="flex items-center gap-2">
          <svg
            v-if="lastCapture.success"
            class="w-4 h-4 flex-shrink-0"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
          </svg>
          <svg
            v-else
            class="w-4 h-4 flex-shrink-0"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
          <span class="truncate">
            {{ lastCapture.success ? lastCapture.filename : lastCapture.error }}
          </span>
        </div>
        <p class="text-xs opacity-70 mt-1 ml-6">
          {{ formatTime(lastCapture.timestamp) }}
        </p>
      </div>

      <!-- Camera State Info -->
      <div
        v-if="!camera.connected"
        class="text-center text-camera-muted text-sm"
      >
        Connect camera to capture
      </div>
    </div>
  </div>
</template>
