<script setup>
import { ref } from 'vue'
import { useCameraStore } from '../stores/camera'

const camera = useCameraStore()
const dismissed = ref(false)

function dismiss() {
  dismissed.value = true
}
</script>

<template>
  <Transition
    enter-active-class="transition-all duration-300 ease-out"
    enter-from-class="opacity-0 -translate-y-2"
    enter-to-class="opacity-100 translate-y-0"
    leave-active-class="transition-all duration-200 ease-in"
    leave-from-class="opacity-100 translate-y-0"
    leave-to-class="opacity-0 -translate-y-2"
  >
    <div
      v-if="camera.connected && !dismissed"
      class="bg-camera-warning/10 border border-camera-warning/30 rounded-lg px-4 py-3"
    >
      <div class="flex items-start gap-3">
        <!-- Warning Icon -->
        <svg
          class="w-5 h-5 text-camera-warning flex-shrink-0 mt-0.5"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
          />
        </svg>

        <!-- Warning Content -->
        <div class="flex-1">
          <h3 class="font-medium text-camera-warning">Mode Dial Requirement</h3>
          <p class="text-sm text-camera-text/80 mt-1">
            Ensure your camera's mode dial is set to <strong>P</strong>, <strong>A</strong>, <strong>S</strong>, or <strong>M</strong> mode.
            Auto and Scene modes will cause settings changes to silently fail.
          </p>
          <div class="flex gap-6 mt-3 text-xs">
            <div class="flex items-center gap-1.5">
              <span class="w-6 h-6 flex items-center justify-center bg-camera-success/20 text-camera-success rounded font-bold">P</span>
              <span class="text-camera-muted">Program</span>
            </div>
            <div class="flex items-center gap-1.5">
              <span class="w-6 h-6 flex items-center justify-center bg-camera-success/20 text-camera-success rounded font-bold">A</span>
              <span class="text-camera-muted">Aperture</span>
            </div>
            <div class="flex items-center gap-1.5">
              <span class="w-6 h-6 flex items-center justify-center bg-camera-success/20 text-camera-success rounded font-bold">S</span>
              <span class="text-camera-muted">Shutter</span>
            </div>
            <div class="flex items-center gap-1.5">
              <span class="w-6 h-6 flex items-center justify-center bg-camera-success/20 text-camera-success rounded font-bold">M</span>
              <span class="text-camera-muted">Manual</span>
            </div>
          </div>
        </div>

        <!-- Dismiss Button -->
        <button
          @click="dismiss"
          class="text-camera-muted hover:text-camera-text transition-colors p-1"
          title="Dismiss"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  </Transition>
</template>
